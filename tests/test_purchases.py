"""Offline contract tests: no AWS clients, credentials or network access."""

import base64
import copy
import importlib.util
import json
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]


def load_lambda(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "lambdas" / name / "index.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


producer = load_lambda("create_purchase")
worker = load_lambda("purchase_worker")
ARN = "arn:aws:states:us-east-1:123456789012:stateMachine:purchase"
OTHER_ARN = "arn:aws:states:us-east-1:123456789012:stateMachine:replacement"
ENV = {
    "EVENTS_TABLE": "events", "ORDERS_TABLE": "orders",
    "PURCHASE_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789012/purchases",
    "WORKFLOW_ARN": ARN,
}


def aws_error(code):
    return ClientError({"Error": {"Code": code, "Message": "Test failure"}}, "TestOperation")


class Orders:
    """Model the conditional operations, including concurrent first deliveries."""

    def __init__(self):
        self.items = {}
        self.lock = threading.Lock()
        self.fail_update_once = False

    def put_item(self, **kwargs):
        assert kwargs["ConditionExpression"] == "attribute_not_exists(orderId)"
        item = kwargs["Item"]
        with self.lock:
            if item["orderId"] in self.items:
                raise aws_error("ConditionalCheckFailedException")
            self.items[item["orderId"]] = copy.deepcopy(item)

    def get_item(self, **kwargs):
        assert kwargs["ConsistentRead"] is True
        with self.lock:
            item = self.items.get(kwargs["Key"]["orderId"])
            return {"Item": copy.deepcopy(item)} if item else {}

    def update_item(self, **kwargs):
        with self.lock:
            if self.fail_update_once:
                self.fail_update_once = False
                raise aws_error("ProvisionedThroughputExceededException")
            item = self.items[kwargs["Key"]["orderId"]]
            values = kwargs["ExpressionAttributeValues"]
            assert kwargs["ConditionExpression"] == "requestFingerprint = :fingerprint"
            if item["requestFingerprint"] != values[":fingerprint"]:
                raise aws_error("ConditionalCheckFailedException")
            item.update(dispatchStatus=values[":started"], executionArn=values[":arn"])


class PurchaseTests(unittest.TestCase):
    def setUp(self):
        self.orders = Orders()
        self.events = Mock()
        self.events.get_item.return_value = {"Item": {"eventId": "event-1", "capacity": Decimal(2)}}
        self.ddb = Mock()
        self.ddb.Table.side_effect = {"orders": self.orders, "events": self.events}.__getitem__
        self.sqs = Mock()
        self.sfn = Mock()
        self.sfn.start_execution.return_value = {
            "executionArn": "arn:aws:states:us-east-1:123456789012:execution:purchase:order-1"
        }
        self.env_patch = patch.dict(os.environ, ENV, clear=True)
        self.resource_patch = patch.object(producer.boto3, "resource", return_value=self.ddb)
        self.client_patch = patch.object(
            producer.boto3, "client", side_effect={"sqs": self.sqs, "stepfunctions": self.sfn}.__getitem__
        )
        for patcher in (self.env_patch, self.resource_patch, self.client_patch):
            patcher.start()
            self.addCleanup(patcher.stop)

    def request(self, data=None, user="user-1", encoded=False):
        body = json.dumps(data if data is not None else {
            "eventId": "event-1", "seatId": "1", "idempotencyKey": "request-1"
        })
        if encoded:
            body = base64.b64encode(body.encode()).decode()
        return {
            "version": "2.0", "isBase64Encoded": encoded, "body": body,
            "requestContext": {"http": {"method": "POST"}, "authorizer": {"jwt": {"claims": {"sub": user}}}},
        }

    def record(self, order=None, message_id="message-1"):
        return {"messageId": message_id, "body": json.dumps(order if order is not None else {
            "orderId": "order-1", "userId": "user-1", "eventId": "event-1", "seatId": "1"
        })}

    def run_worker(self, *records):
        return worker.lambda_handler({"Records": list(records or [self.record()])}, None)

    def assert_failed(self, result, *ids):
        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": value} for value in ids]})

    def test_authenticated_intake_enqueues_only_trusted_fields(self):
        response = producer.handler(self.request(), None)
        self.assertEqual(response["statusCode"], 202)
        order = json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])
        self.assertEqual(set(order), set(worker.REQUIRED_FIELDS))
        self.assertEqual(order["userId"], "user-1")
        self.assertEqual(order["orderId"], json.loads(response["body"])["orderId"])
        self.assertEqual(len(order["orderId"]), 73)
        self.assertEqual(self.sqs.send_message.call_args.kwargs["QueueUrl"], ENV["PURCHASE_QUEUE_URL"])

    def test_base64_http_body(self):
        self.assertEqual(producer.handler(self.request(encoded=True), None)["statusCode"], 202)

    def test_invalid_requests_never_enqueue(self):
        for data in (
            [], None, {}, {"eventId": "event-1", "seatId": 1, "idempotencyKey": "k"},
            {"eventId": " ", "seatId": "1", "idempotencyKey": "k"},
            {"eventId": "event-1", "seatId": "01", "idempotencyKey": "k"},
            {"eventId": "event-1", "seatId": "A12", "idempotencyKey": "k"},
            {"eventId": "event-1", "seatId": "1", "idempotencyKey": ""},
            {"eventId": "event-1", "seatId": "1", "idempotencyKey": "k", "userId": "forged"},
            {"eventId": "event-1", "seatId": "1", "idempotencyKey": "k", "forceFail": True},
        ):
            with self.subTest(data=data):
                request = self.request()
                request["body"] = json.dumps(data)
                self.assertEqual(producer.handler(request, None)["statusCode"], 400)
        for body, encoded in (("{bad", False), ("!bad", True), ("x" * 4097, False)):
            request = self.request()
            request.update(body=body, isBase64Encoded=encoded)
            self.assertEqual(producer.handler(request, None)["statusCode"], 400)
        self.sqs.send_message.assert_not_called()

    def test_missing_identity_is_unauthorized(self):
        request = self.request()
        request["requestContext"].pop("authorizer")
        self.assertEqual(producer.handler(request, None)["statusCode"], 401)
        self.sqs.send_message.assert_not_called()

    def test_event_validation(self):
        self.events.get_item.return_value = {}
        self.assertEqual(producer.handler(self.request(), None)["statusCode"], 404)
        for capacity in (0, -1, True, None, "2", Decimal("1.5"), Decimal("NaN"), Decimal("Infinity")):
            with self.subTest(capacity=capacity):
                self.events.get_item.return_value = {"Item": {"capacity": capacity}}
                self.assertEqual(producer.handler(self.request(), None)["statusCode"], 400)
        self.events.get_item.return_value = {"Item": {"capacity": 2, "source": "ticketmaster"}}
        self.assertEqual(producer.handler(self.request(), None)["statusCode"], 400)
        self.events.get_item.return_value = {"Item": {"capacity": 2}}
        self.assertEqual(producer.handler(self.request({
            "eventId": "event-1", "seatId": "3", "idempotencyKey": "k"
        }), None)["statusCode"], 400)
        self.sqs.send_message.assert_not_called()

    def test_queue_or_database_failure_returns_retryable_response(self):
        self.sqs.send_message.side_effect = aws_error("ServiceUnavailable")
        self.assertEqual(producer.handler(self.request(), None)["statusCode"], 503)
        self.sqs.send_message.side_effect = None
        self.events.get_item.side_effect = aws_error("AccessDeniedException")
        self.assertEqual(producer.handler(self.request(), None)["statusCode"], 503)

    def test_repeated_requests_have_same_order_but_users_are_isolated(self):
        first = producer.handler(self.request(), None)
        second = producer.handler(self.request(), None)
        other = producer.handler(self.request(user="user-2"), None)
        self.assertEqual(json.loads(first["body"])["orderId"], json.loads(second["body"])["orderId"])
        self.assertNotEqual(json.loads(first["body"])["orderId"], json.loads(other["body"])["orderId"])

    def test_end_to_end_duplicate_request_does_not_restart_workflow(self):
        response = producer.handler(self.request(), None)
        record = {"messageId": "m", "body": self.sqs.send_message.call_args.kwargs["MessageBody"]}
        self.assert_failed(self.run_worker(record))
        self.sqs.reset_mock()
        self.assertEqual(producer.handler(self.request(), None), response)
        self.sqs.send_message.assert_not_called()
        self.assert_failed(self.run_worker(record))
        self.sfn.start_execution.assert_called_once()

    def test_key_reuse_with_changed_payload_returns_conflict_after_persistence(self):
        producer.handler(self.request(), None)
        self.run_worker({"messageId": "m", "body": self.sqs.send_message.call_args.kwargs["MessageBody"]})
        self.sqs.reset_mock()
        response = producer.handler(self.request({
            "eventId": "event-1", "seatId": "2", "idempotencyKey": "request-1"
        }), None)
        self.assertEqual(response["statusCode"], 409)
        self.sqs.send_message.assert_not_called()

    def test_worker_persists_complete_order_and_exact_input_before_start(self):
        def started(**kwargs):
            item = self.orders.items["order-1"]
            self.assertEqual(item["userId"], "user-1")
            self.assertEqual(item["orderStatus"], "PENDING")
            self.assertEqual(item["dispatchStatus"], "PENDING")
            self.assertEqual(kwargs, {"stateMachineArn": ARN, "name": "order-1", "input": item["workflowInput"]})
            return {"executionArn": "execution-1"}
        self.sfn.start_execution.side_effect = started
        self.assert_failed(self.run_worker())
        self.assertEqual(self.orders.items["order-1"]["dispatchStatus"], "STARTED")

    def test_start_failure_retries_saved_input_and_original_workflow(self):
        self.sfn.start_execution.side_effect = aws_error("ThrottlingException")
        self.assert_failed(self.run_worker(), "message-1")
        original = copy.deepcopy(self.orders.items["order-1"])
        self.sfn.start_execution.side_effect = None
        with patch.dict(os.environ, {"WORKFLOW_ARN": OTHER_ARN}):
            self.assert_failed(self.run_worker())
        kwargs = self.sfn.start_execution.call_args.kwargs
        self.assertEqual(kwargs["stateMachineArn"], ARN)
        self.assertEqual(kwargs["input"], original["workflowInput"])
        self.assertEqual(self.orders.items["order-1"]["createdAt"], original["createdAt"])

    def test_lost_start_response_retries_identical_execution(self):
        # The remote side accepted the first call; its response did not arrive.
        from botocore.exceptions import ReadTimeoutError

        self.sfn.start_execution.side_effect = ReadTimeoutError(endpoint_url="https://states.example")
        self.assert_failed(self.run_worker(), "message-1")
        first_call = self.sfn.start_execution.call_args
        self.sfn.start_execution.side_effect = None
        self.assert_failed(self.run_worker())
        self.assertEqual(self.sfn.start_execution.call_args, first_call)
        self.assertEqual(self.orders.items["order-1"]["dispatchStatus"], "STARTED")

    def test_identical_pending_request_is_requeued_after_start_failure(self):
        response = producer.handler(self.request(), None)
        record = {"messageId": "m", "body": self.sqs.send_message.call_args.kwargs["MessageBody"]}
        self.sfn.start_execution.side_effect = aws_error("ThrottlingException")
        self.assert_failed(self.run_worker(record), "m")
        self.sqs.reset_mock()
        self.events.get_item.side_effect = AssertionError("Persisted retries must not revalidate inventory")
        self.assertEqual(producer.handler(self.request(), None), response)
        self.sqs.send_message.assert_called_once()

    def test_conflicting_delivery_does_not_overwrite_or_start(self):
        self.assert_failed(self.run_worker())
        original = copy.deepcopy(self.orders.items)
        changed = json.loads(self.record()["body"])
        changed["seatId"] = "2"
        self.assert_failed(self.run_worker(self.record(changed)), "message-1")
        self.assertEqual(self.orders.items, original)
        self.sfn.start_execution.assert_called_once()

    def test_conflicting_requests_before_worker_are_resolved_conditionally(self):
        first = producer.handler(self.request(), None)
        producer.handler(self.request({"eventId": "event-1", "seatId": "2", "idempotencyKey": "request-1"}), None)
        messages = [call.kwargs["MessageBody"] for call in self.sqs.send_message.call_args_list]
        result = self.run_worker(*[{"messageId": str(i), "body": body} for i, body in enumerate(messages)])
        self.assert_failed(result, "1")
        order_id = json.loads(first["body"])["orderId"]
        self.assertEqual(self.orders.items[order_id]["seatId"], "1")
        self.sfn.start_execution.assert_called_once()

    def test_unknown_or_invalid_worker_fields_are_rejected(self):
        good = json.loads(self.record()["body"])
        invalid = [[], {}, {**good, "seatId": "01"}, {**good, "forceFail": True},
                   {**good, "orderId": "invalid name"}, {**good, "orderId": "x" * 81},
                   {**good, "userId": " "}, {**good, "seatId": 1}]
        for order in invalid:
            with self.subTest(order=order):
                self.assert_failed(self.run_worker(self.record(order)), "message-1")
        self.assert_failed(self.run_worker({"messageId": "bad", "body": "{bad"}), "bad")
        self.assertEqual(self.orders.items, {})
        self.sfn.start_execution.assert_not_called()

    def test_missing_or_qualified_arn_fails_closed(self):
        for arn in ("", ARN + ":alias", "invalid"):
            with self.subTest(arn=arn), patch.dict(os.environ, {"WORKFLOW_ARN": arn, "DRY_RUN": "true"}):
                self.assert_failed(self.run_worker(), "message-1")
        self.assertEqual(self.orders.items, {})
        self.sfn.start_execution.assert_not_called()

    def test_partial_batch_failure(self):
        result = self.run_worker({"messageId": "bad", "body": "null"}, self.record())
        self.assert_failed(result, "bad")
        self.sfn.start_execution.assert_called_once()

    def test_database_failure_never_starts_execution(self):
        with patch.object(self.orders, "put_item", side_effect=aws_error("AccessDeniedException")):
            self.assert_failed(self.run_worker(), "message-1")
        self.sfn.start_execution.assert_not_called()

    def test_completed_or_failed_execution_is_reconciled_after_update_failure(self):
        for status in ("SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED", "RUNNING"):
            with self.subTest(status=status):
                self.orders.items.clear()
                self.sfn.start_execution.side_effect = None
                self.orders.fail_update_once = True
                self.assert_failed(self.run_worker(), "message-1")
                item = self.orders.items["order-1"]
                item.update(orderStatus="WORKFLOW_OWNED", ticketStatus="issued")
                self.sfn.start_execution.side_effect = aws_error("ExecutionAlreadyExists")
                self.sfn.describe_execution.return_value = {
                    "input": item["workflowInput"], "stateMachineArn": ARN, "status": status,
                }
                self.assert_failed(self.run_worker())
                self.assertEqual(item["dispatchStatus"], "STARTED")
                self.assertEqual(item["orderStatus"], "WORKFLOW_OWNED")
                self.assertEqual(item["ticketStatus"], "issued")
                self.sfn.describe_execution.assert_called_with(
                    executionArn="arn:aws:states:us-east-1:123456789012:execution:purchase:order-1"
                )

    def test_existing_execution_must_match_identity(self):
        self.sfn.start_execution.side_effect = aws_error("ExecutionAlreadyExists")
        for description in ({"input": "{}", "stateMachineArn": ARN},
                            {"input": json.dumps(json.loads(self.record()["body"]), sort_keys=True, separators=(",", ":")),
                             "stateMachineArn": OTHER_ARN}):
            self.sfn.describe_execution.return_value = description
            self.assert_failed(self.run_worker(), "message-1")
            self.assertEqual(self.orders.items["order-1"]["dispatchStatus"], "PENDING")

    def test_describe_failure_does_not_acknowledge(self):
        self.sfn.start_execution.side_effect = aws_error("ExecutionAlreadyExists")
        self.sfn.describe_execution.side_effect = aws_error("AccessDeniedException")
        self.assert_failed(self.run_worker(), "message-1")
        self.assertEqual(self.orders.items["order-1"]["dispatchStatus"], "PENDING")

    def test_old_pending_order_needs_reconciliation_but_started_is_durable(self):
        self.sfn.start_execution.side_effect = aws_error("ThrottlingException")
        self.assert_failed(self.run_worker(), "message-1")
        item = self.orders.items["order-1"]
        self.sfn.start_execution.reset_mock(side_effect=True)
        with patch.object(worker.time, "time", return_value=item["createdAt"] + worker.MAX_PENDING_AGE):
            self.assert_failed(self.run_worker(), "message-1")
            self.sfn.start_execution.assert_not_called()
            item["dispatchStatus"] = "STARTED"
            self.assert_failed(self.run_worker())

    def test_simultaneous_deliveries_create_one_order_and_one_execution(self):
        barrier = threading.Barrier(2)
        executions = {}
        lock = threading.Lock()

        def start(**kwargs):
            barrier.wait(timeout=5)
            with lock:
                previous = executions.setdefault(kwargs["name"], kwargs["input"])
                self.assertEqual(previous, kwargs["input"])
            return {"executionArn": "execution-1"}

        self.sfn.start_execution.side_effect = start
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.run_worker(), range(2)))
        for result in results:
            self.assert_failed(result)
        self.assertEqual(len(self.orders.items), 1)
        self.assertEqual(len(executions), 1)


if __name__ == "__main__":
    unittest.main()
