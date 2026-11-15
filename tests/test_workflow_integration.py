"""Exercise real SDK requests/conditions against Moto's in-memory AWS emulator."""

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import Mock, patch

import boto3
from botocore.exceptions import ClientError, ReadTimeoutError
from moto import mock_aws

from test_purchases import ROOT, load_lambda, producer, worker

sys.path.insert(0, str(ROOT / "lambdas" / "workflow_common"))
import purchase_common as common

reserve = load_lambda("reserve_seat")
payment = load_lambda("take_payment")
ticket = load_lambda("generate_ticket")
release = load_lambda("release_seat")
email = load_lambda("send_email")


class WorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {
            "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
            "AWS_DEFAULT_REGION": "us-east-1", "AWS_EC2_METADATA_DISABLED": "true",
            "EVENTS_TABLE": "events", "SEATS_TABLE": "seats", "ORDERS_TABLE": "orders",
            "WORKFLOW_ARN": "arn:aws:states:us-east-1:123456789012:stateMachine:purchase",
            "HOLD_SECONDS": "900", "NOTIFY_EMAIL": "demo@example.com",
        }, clear=True)
        env.start()
        self.addCleanup(env.stop)
        mock = mock_aws()
        mock.start()
        self.addCleanup(mock.stop)
        self.ddb = boto3.resource("dynamodb")
        for name, keys in (("events", ["eventId"]), ("orders", ["orderId"]),
                           ("seats", ["eventId", "seatId"])):
            self.ddb.create_table(
                TableName=name, BillingMode="PAY_PER_REQUEST",
                KeySchema=[{"AttributeName": key, "KeyType": "HASH" if i == 0 else "RANGE"}
                           for i, key in enumerate(keys)],
                AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"} for key in keys],
            )
        self.events = self.ddb.Table("events")
        self.orders = self.ddb.Table("orders")
        self.seats = self.ddb.Table("seats")
        self.events.put_item(Item={"eventId": "event-1", "capacity": 2})
        self.client = boto3.client("dynamodb")
        self.clock = patch("time.time", return_value=1800000000)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def seed(self, order_id="order-1", seat="1", user="user-1"):
        order = {"orderId": order_id, "userId": user, "eventId": "event-1", "seatId": seat}
        self.orders.put_item(Item={**order, "orderStatus": "PENDING", "dispatchStatus": "STARTED"})
        return order

    def saved(self, order):
        return self.orders.get_item(Key={"orderId": order["orderId"]}, ConsistentRead=True).get("Item")

    def seat(self, order):
        return self.seats.get_item(Key=common.seat_key(order), ConsistentRead=True).get("Item")

    def pay(self, order):
        reserve.handler(order, None)
        return payment.handler(order, None)

    def confirm(self, order):
        self.pay(order)
        return ticket.handler(order, None)

    def fail(self, order, stage="PAYMENT", error="PaymentFailed"):
        return release.handler({"order": {**order, "error": {"Error": error}}, "failureStage": stage}, None)

    @contextmanager
    def transaction_hook(self, before=None, lose_response=False):
        proxy = Mock(wraps=self.client)

        def transact(**kwargs):
            # Nested operations use the unwrapped client, not this test hook.
            if before:
                with patch.object(common.boto3, "client", return_value=self.client):
                    before()
            result = self.client.transact_write_items(**kwargs)
            if lose_response:
                raise ReadTimeoutError(endpoint_url="https://local-emulator.invalid")
            return result

        proxy.transact_write_items.side_effect = transact
        with patch.object(common.boto3, "client", return_value=proxy):
            yield proxy

    def test_api_queue_worker_and_full_workflow_preserve_order_and_replay(self):
        sqs = boto3.client("sqs")
        queue = sqs.create_queue(QueueName="purchases")["QueueUrl"]
        os.environ["PURCHASE_QUEUE_URL"] = queue
        request = {"version": "2.0", "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "user-1"}}}},
                   "body": json.dumps({"eventId": "event-1", "seatId": "1", "idempotencyKey": "retry-key"})}
        response = producer.handler(request, None)
        self.assertEqual(response["statusCode"], 202)
        message = sqs.receive_message(QueueUrl=queue)["Messages"][0]
        record = {"messageId": message["MessageId"], "body": message["Body"]}
        sfn = Mock()
        sfn.start_execution.side_effect = lambda **args: {
            "executionArn": "arn:aws:states:us-east-1:123456789012:execution:purchase:" + args["name"]
        }
        original_client = boto3.client

        def client(service, *args, **kwargs):
            return sfn if service == "stepfunctions" else original_client(service, *args, **kwargs)

        with patch.object(worker.boto3, "client", side_effect=client):
            self.assertEqual(worker.lambda_handler({"Records": [record]}, None), {"batchItemFailures": []})
            order = json.loads(sfn.start_execution.call_args.kwargs["input"])
            original = self.saved(order)
            state = dict(order)
            state["reserve"] = reserve.handler(state, None)
            state["payment"] = payment.handler(state, None)
            state = ticket.handler(state, None)
            ses = Mock()
            with patch.object(email.boto3, "client", side_effect=lambda service: ses if service == "ses" else self.client):
                state["email"] = email.handler(state, None)
                self.assertEqual(email.handler(state, None)["emailStatus"], "sent")
            ses.send_email.assert_called_once()
            self.assertEqual(payment.handler(order, None)["paymentId"], state["payment"]["paymentId"])
            self.assertEqual(ticket.handler(order, None)["qrPayload"], state["qrPayload"])
            self.assertEqual(reserve.handler(order, None)["seatStatus"], "sold")
            self.assertEqual(worker.lambda_handler({"Records": [record]}, None), {"batchItemFailures": []})
            sfn.start_execution.assert_called_once()
        saved = self.saved(order)
        self.assertEqual(saved["orderStatus"], "CONFIRMED")
        self.assertEqual(saved["emailStatus"], "sent")
        self.assertEqual(self.seat(order)["status"], "sold")
        self.assertNotIn("holdExpiresAt", self.seat(order))
        for field in ("userId", "requestFingerprint", "workflowInput", "workflowArn", "dispatchStatus", "executionArn"):
            self.assertEqual(saved[field], original[field])

    def test_competing_orders_cannot_sell_same_seat(self):
        first, second = self.seed(), self.seed("order-2")
        self.confirm(first)
        with patch("time.time", return_value=1800005000):
            with self.assertRaises(reserve.SeatUnavailable):
                reserve.handler(second, None)
        result = self.fail(second, "RESERVATION", "SeatUnavailable")
        self.assertEqual(result["orderStatus"], "REJECTED")
        self.assertEqual(self.seat(first)["heldBy"], first["orderId"])
        self.assertEqual(self.seat(first)["status"], "sold")

    def test_distinct_canonical_seats_obey_capacity(self):
        for seat in ("1", "2"):
            self.confirm(self.seed("order-" + seat, seat))
        invalid = self.seed("order-3", "3")
        with self.assertRaises(reserve.SeatUnavailable):
            reserve.handler(invalid, None)
        self.assertEqual(self.seats.scan()["Count"], 2)

    def test_invalid_seat_aliases_cannot_create_extra_inventory(self):
        for value in ("01", "+1", "1.0", "0", "-1", " 1", "A12", 1, True):
            with self.subTest(value=value):
                order = self.seed(seat=value)
                with self.assertRaises(common.OrderMismatch):
                    reserve.handler(order, None)
        self.assertEqual(self.seats.scan()["Count"], 0)

    def test_invalid_capacity_and_external_events_fail_closed(self):
        order = self.seed()
        for capacity in (0, -1, True, Decimal("1.5"), "2"):
            with self.subTest(capacity=capacity):
                self.events.put_item(Item={"eventId": "event-1", "capacity": capacity})
                with self.assertRaises(reserve.SeatUnavailable):
                    reserve.handler(order, None)
        self.events.put_item(Item={"eventId": "event-1", "capacity": 2, "source": "ticketmaster"})
        with self.assertRaises(reserve.SeatUnavailable):
            reserve.handler(order, None)
        self.events.delete_item(Key={"eventId": "event-1"})
        with self.assertRaises(reserve.SeatUnavailable):
            reserve.handler(order, None)
        self.assertIsNone(self.seat(order))
        self.assertEqual(self.saved(order)["orderStatus"], "PENDING")

    def test_missing_event_table_configuration_cannot_disable_capacity_check(self):
        order = self.seed()
        del os.environ["EVENTS_TABLE"]
        with self.assertRaises(KeyError):
            reserve.handler(order, None)
        self.assertIsNone(self.seat(order))

    def test_capacity_change_between_read_and_transaction_rolls_back_hold(self):
        order = self.seed()
        def change_capacity():
            self.events.put_item(Item={"eventId": "event-1", "capacity": 0})
        with self.transaction_hook(before=change_capacity):
            with self.assertRaises(reserve.SeatUnavailable):
                reserve.handler(order, None)
        self.assertIsNone(self.seat(order))
        self.assertEqual(self.saved(order)["orderStatus"], "PENDING")

    def test_repeated_reservation_and_lost_response_are_safe(self):
        order = self.seed()
        with self.transaction_hook(lose_response=True):
            with self.assertRaises(ReadTimeoutError):
                reserve.handler(order, None)
        self.assertEqual(reserve.handler(order, None)["seatStatus"], "held")
        self.assertEqual(self.seats.scan()["Count"], 1)
        self.assertEqual(self.saved(order)["orderStatus"], "RESERVED")

    def test_payment_response_loss_does_not_repeat_payment(self):
        order = self.seed()
        reserve.handler(order, None)
        with self.transaction_hook(lose_response=True):
            with self.assertRaises(ReadTimeoutError):
                payment.handler(order, None)
        original = copy.deepcopy(self.saved(order))
        with patch("time.time", return_value=1800000005):
            result = payment.handler(order, None)
        self.assertEqual(result["paymentId"], original["paymentId"])
        self.assertEqual(result["paidAt"], original["paidAt"])
        self.assertEqual(self.saved(order), original)

    def test_ticket_response_loss_does_not_regenerate_or_resell(self):
        order = self.seed()
        self.pay(order)
        with self.transaction_hook(lose_response=True):
            with self.assertRaises(ReadTimeoutError):
                ticket.handler(order, None)
        original = copy.deepcopy(self.saved(order))
        with patch("time.time", return_value=1800005000):
            result = ticket.handler(order, None)
        self.assertEqual(result["qrPayload"], original["qrPayload"])
        self.assertEqual(self.saved(order), original)
        self.assertEqual(self.seat(order)["status"], "sold")

    def test_failed_order_update_does_not_partially_sell_seat(self):
        order = self.seed()
        self.pay(order)
        def change_order():
            self.orders.update_item(Key={"orderId": order["orderId"]},
                                    UpdateExpression="SET orderStatus = :s",
                                    ExpressionAttributeValues={":s": "REVIEW_REQUIRED"})
        with self.transaction_hook(before=change_order):
            with self.assertRaises(ticket.SeatLost):
                ticket.handler(order, None)
        self.assertEqual(self.seat(order)["status"], "held")
        self.assertNotIn("ticketStatus", self.saved(order))

    def test_simulated_payment_failure_releases_only_its_hold(self):
        order = self.seed()
        reserve.handler(order, None)
        with self.assertRaises(payment.PaymentFailed):
            payment.handler({**order, "forceFail": True}, None)
        self.assertTrue(self.fail(order)["released"])
        self.assertEqual(self.seat(order)["status"], "free")
        self.assertEqual(self.saved(order)["orderStatus"], "FAILED")
        self.assertFalse(self.fail(order)["released"])
        with self.assertRaises(payment.PaymentFailed):
            payment.handler(order, None)

    def test_late_release_cannot_free_another_orders_hold(self):
        first, second = self.seed(), self.seed("order-2")
        reserve.handler(first, None)
        with patch("time.time", return_value=1800001000):
            reserve.handler(second, None)
            self.assertFalse(self.fail(first)["released"])
        self.assertEqual(self.seat(second)["heldBy"], second["orderId"])
        self.assertEqual(self.seat(second)["status"], "held")

    def test_late_release_never_frees_confirmed_seat(self):
        order = self.seed()
        self.confirm(order)
        self.assertFalse(self.fail(order)["released"])
        self.assertEqual(self.saved(order)["orderStatus"], "CONFIRMED")
        self.assertEqual(self.seat(order)["status"], "sold")

    def test_paid_order_losing_expired_hold_requires_review(self):
        first, second = self.seed(), self.seed("order-2")
        self.pay(first)
        with patch("time.time", return_value=1800001000):
            reserve.handler(second, None)
            with self.assertRaises(ticket.SeatLost):
                ticket.handler(first, None)
            self.assertFalse(self.fail(first, "FULFILLMENT", "SeatLost")["released"])
            payment.handler(second, None)
            ticket.handler(second, None)
        self.assertEqual(self.saved(first)["orderStatus"], "REVIEW_REQUIRED")
        self.assertEqual(self.saved(first)["paymentStatus"], "paid")
        self.assertNotIn("ticketStatus", self.saved(first))
        self.assertEqual(self.seat(second)["heldBy"], second["orderId"])
        self.assertEqual(self.seat(second)["status"], "sold")

    def test_expired_hold_cannot_be_paid_or_confirmed(self):
        order = self.seed()
        reserve.handler(order, None)
        with patch("time.time", return_value=1800001000):
            with self.assertRaises(payment.PaymentFailed):
                payment.handler(order, None)
        self.assertNotIn("paymentStatus", self.saved(order))
        self.assertEqual(self.seat(order)["status"], "held")

    def test_payment_winning_race_prevents_unpaid_compensation(self):
        order = self.seed()
        reserve.handler(order, None)
        with self.transaction_hook(before=lambda: payment.handler(order, None)):
            with self.assertRaises(common.ConcurrentOrderChange):
                self.fail(order)
        self.assertFalse(self.fail(order)["released"])
        self.assertEqual(self.saved(order)["orderStatus"], "REVIEW_REQUIRED")
        self.assertEqual(self.seat(order)["status"], "held")

    def test_compensation_winning_race_prevents_late_payment(self):
        order = self.seed()
        reserve.handler(order, None)
        with self.transaction_hook(before=lambda: self.fail(order)):
            with self.assertRaises(payment.PaymentFailed):
                payment.handler(order, None)
        self.assertEqual(self.saved(order)["orderStatus"], "FAILED")
        self.assertNotIn("paymentStatus", self.saved(order))
        self.assertEqual(self.seat(order)["status"], "free")

    def test_email_failure_is_persisted_without_releasing_paid_inventory(self):
        order = self.seed()
        state = self.confirm(order)
        ses = Mock()
        ses.send_email.side_effect = RuntimeError("SES unavailable")
        with patch.object(email.boto3, "client", side_effect=lambda service: ses if service == "ses" else self.client):
            self.assertEqual(email.handler(state, None)["emailStatus"], "not_sent")
        self.assertEqual(self.saved(order)["emailStatus"], "not_sent")
        self.assertEqual(self.saved(order)["orderStatus"], "CONFIRMED")
        self.assertEqual(self.seat(order)["status"], "sold")

    def test_notification_catch_cannot_downgrade_sent(self):
        order = self.seed()
        state = self.confirm(order)
        ses = Mock()
        with patch.object(email.boto3, "client", side_effect=lambda service: ses if service == "ses" else self.client):
            email.handler(state, None)
        self.assertEqual(self.fail(order, "NOTIFICATION")["emailStatus"], "sent")
        self.assertEqual(self.saved(order)["emailStatus"], "sent")

    def test_workflow_cannot_create_or_mutate_missing_or_mismatched_order(self):
        order = self.seed()
        for bad in ({**order, "userId": "other-user"}, {**order, "orderId": "missing"}):
            with self.assertRaises(common.OrderMismatch):
                reserve.handler(bad, None)
        self.assertEqual(self.saved(order)["orderStatus"], "PENDING")
        self.assertIsNone(self.seat(order))

    def test_infrastructure_cancellation_is_not_business_rejection(self):
        order = self.seed()
        exc = ClientError({"Error": {"Code": "TransactionCanceledException"},
                           "CancellationReasons": [{"Code": "ProvisionedThroughputExceeded"}]}, "TransactWriteItems")
        with self.transaction_hook() as proxy:
            proxy.transact_write_items.side_effect = exc
            with self.assertRaises(ClientError):
                reserve.handler(order, None)
        self.assertEqual(self.saved(order)["orderStatus"], "PENDING")


class WorkflowPackagingTests(unittest.TestCase):
    def test_every_workflow_archive_includes_shared_helper(self):
        config = (ROOT / "infra" / "workflow.tf").read_text()
        for name in ("reserve_seat", "take_payment", "generate_ticket", "release_seat", "send_email"):
            archive = re.search(r'data "archive_file" "' + name + r'" \{(.*?)\n\}', config, re.S).group(1)
            self.assertIn(f'/lambdas/{name}/index.py', archive)
            self.assertIn('/lambdas/workflow_common/purchase_common.py', archive)
            self.assertIn('filename = "purchase_common.py"', archive)


@unittest.skipUnless(shutil.which("terraform"), "Terraform is required to evaluate the ASL definition")
class WorkflowDefinitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Evaluate the actual HCL/locals offline, replacing only resource ARNs.
        # This temp configuration has no providers, backend, AWS calls or state.
        config = (ROOT / "infra" / "workflow.tf").read_text()
        retry = re.search(r"locals \{(.*?)\n\}", config, re.S).group(1)
        definition = config.split("  definition = ", 1)[1].rsplit("\n}", 1)[0].strip()
        definition = re.sub(
            r"aws_lambda_function\.([a-z_]+)\.arn",
            lambda match: json.dumps("arn:aws:lambda:us-east-1:123456789012:function:" + match[1]),
            definition,
        )
        with tempfile.TemporaryDirectory(prefix="ticketing-asl-") as directory:
            from pathlib import Path
            Path(directory, "main.tf").write_text("locals {\n" + retry + "\ndefinition = " + definition + "\n}\n")
            result = subprocess.run(
                ["terraform", "-chdir=" + directory, "console", "-no-color"],
                input="local.definition\n", capture_output=True, text=True, timeout=20, check=True,
            )
        cls.definition = json.loads(json.loads(result.stdout))

    def test_state_graph_has_valid_reachable_targets(self):
        states = self.definition["States"]
        reached, pending = set(), [self.definition["StartAt"]]
        while pending:
            name = pending.pop()
            self.assertIn(name, states)
            if name in reached:
                continue
            reached.add(name)
            state = states[name]
            pending.extend([state["Next"]] if "Next" in state else [])
            pending.extend(catcher["Next"] for catcher in state.get("Catch", []))
        self.assertEqual(reached, set(states))

    def test_failure_routes_keep_payment_and_notification_outcomes_separate(self):
        states = self.definition["States"]
        for source, target, stage in (
            ("ReserveSeat", "RejectOrder", "RESERVATION"),
            ("TakePayment", "ReleaseSeat", "PAYMENT"),
            ("GenerateTicket", "ReviewOrder", "FULFILLMENT"),
            ("SendEmail", "RecordNotificationFailure", "NOTIFICATION"),
        ):
            self.assertEqual(states[source]["Catch"][0]["Next"], target)
            self.assertEqual(states[target]["Parameters"], {"order.$": "$", "failureStage": stage})
            self.assertTrue(states[target]["Resource"].endswith(":release_seat"))
        self.assertEqual(states["RecordNotificationFailure"]["Next"], "Succeeded")
        self.assertEqual(states["ReviewOrder"]["Next"], "FulfillmentFailed")

    def test_retries_are_bounded_and_do_not_retry_business_rejections(self):
        for state in self.definition["States"].values():
            if state["Type"] != "Task":
                continue
            retrier = state["Retry"][0]
            self.assertEqual(retrier["MaxAttempts"], 2)
            self.assertIn("ConcurrentOrderChange", retrier["ErrorEquals"])
            for business_error in ("SeatUnavailable", "PaymentFailed", "SeatLost", "States.TaskFailed", "States.ALL"):
                self.assertNotIn(business_error, retrier["ErrorEquals"])
        self.assertLess(self.definition["TimeoutSeconds"], 900)
        self.assertEqual(self.definition["States"]["GenerateTicket"]["ResultPath"], "$")


if __name__ == "__main__":
    unittest.main()
