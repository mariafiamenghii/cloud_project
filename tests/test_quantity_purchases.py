"""Quantity contracts and real DynamoDB conditions exercised through Moto."""
import importlib.util
import json
import os
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import patch

import boto3
from moto import mock_aws
from test_purchases import ROOT, producer, worker, get_order, load_lambda

sys.path.insert(0, str(ROOT / "lambdas/workflow_common"))
import quantity_workflow as flow

spec = importlib.util.spec_from_file_location("migration", ROOT / "scripts/migrate_quantity_inventory.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class QuantityTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {
            "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing", "AWS_DEFAULT_REGION": "us-east-1",
            "AWS_EC2_METADATA_DISABLED": "true", "EVENTS_TABLE": "events", "ORDERS_TABLE": "orders", "SEATS_TABLE": "seats",
            "TICKETS_TABLE": "tickets", "PURCHASE_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789012/queue",
            "WORKFLOW_ARN": "arn:aws:states:us-east-1:123456789012:stateMachine:purchase", "NOTIFY_EMAIL": "",
        }, clear=True)
        env.start(); self.addCleanup(env.stop)
        mock = mock_aws(); mock.start(); self.addCleanup(mock.stop)
        self.ddb = boto3.resource("dynamodb")
        for name, keys in (("events", ["eventId"]), ("orders", ["orderId"]), ("seats", ["eventId", "seatId"]), ("tickets", ["orderId", "ticketId"])):
            self.ddb.create_table(TableName=name, BillingMode="PAY_PER_REQUEST",
                KeySchema=[{"AttributeName": key, "KeyType": "HASH" if index == 0 else "RANGE"} for index, key in enumerate(keys)],
                AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"} for key in keys])
        self.events = self.ddb.Table("events"); self.orders = self.ddb.Table("orders")
        self.events.put_item(Item={"eventId": "event", "capacity": 100, "inventoryVersion": 2, "sold": 0, "reserved": 0, "available": 100, "price": Decimal("25")})
        sqs = boto3.client("sqs"); sqs.create_queue(QueueName="queue")
        reader = patch.object(get_order, "_ddb", self.ddb); reader.start(); self.addCleanup(reader.stop)

    def request(self, q=4, user="buyer-a", key="key", **extra):
        return {"body": json.dumps({"eventId": "event", "quantity": q, "idempotencyKey": key, **extra}),
                "requestContext": {"authorizer": {"jwt": {"claims": {"sub": user}}}}}

    def accept(self, q=4, user="buyer-a", key="key"):
        result = producer.handler(self.request(q, user, key), None)
        self.assertEqual(result["statusCode"], 202, result)
        order_id = json.loads(result["body"])["orderId"]
        saved = self.orders.get_item(Key={"orderId": order_id})["Item"]
        return json.loads(saved["workflowInput"])

    def inventory(self):
        item = self.events.get_item(Key={"eventId": "event"}, ConsistentRead=True)["Item"]
        self.assertEqual(item["capacity"], item["sold"] + item["reserved"] + item["available"])
        self.assertTrue(all(item[k] >= 0 for k in ("sold", "reserved", "available")))
        return {k: int(item[k]) for k in ("sold", "reserved", "available")}

    def lookup(self, order, user=None):
        return get_order.handler({"pathParameters": {"orderId": order["orderId"]},
            "requestContext": {"authorizer": {"jwt": {"claims": {"sub": user or order["userId"]}}}}}, None)

    def fulfill(self, order):
        flow.reserve(order); flow.pay(order); flow.issue(order); flow.notify(order)
        response = self.lookup(order)
        self.assertEqual(response["statusCode"], 200)
        return json.loads(response["body"])

    def test_one_and_four_tickets_and_owner_polling(self):
        for q in (1, 4):
            order = self.accept(q, key=str(q)); result = self.fulfill(order)
            self.assertEqual(result["orderStatus"], "CONFIRMED")
            self.assertEqual(result["quantity"], q)
            self.assertEqual(len(result["tickets"]), q)
            self.assertEqual(len({t["ticketId"] for t in result["tickets"]}), q)
            self.assertEqual(len({t["qrPayload"] for t in result["tickets"]}), q)
            self.assertEqual(result["totalPrice"], 25 * q)
            self.assertEqual(self.lookup(order, "other-buyer")["statusCode"], 404)
        self.assertEqual(self.inventory(), {"sold": 5, "reserved": 0, "available": 95})

    def test_two_customers_four_each_leave_92(self):
        first = self.fulfill(self.accept(user="buyer-a"))
        self.assertEqual(self.inventory()["available"], 96)
        second = self.fulfill(self.accept(user="buyer-b"))
        self.assertEqual(self.inventory(), {"sold": 8, "reserved": 0, "available": 92})
        self.assertEqual(len({t["ticketId"] for r in (first, second) for t in r["tickets"]}), 8)

    def test_validation_auth_and_external_provider(self):
        for value in (0, -1, 1.5, True, "4", None, 21):
            self.assertEqual(producer.handler(self.request(value), None)["statusCode"], 400)
        self.assertEqual(producer.handler(self.request(user=""), None)["statusCode"], 401)
        self.assertEqual(producer.handler(self.request(seatId="4"), None)["statusCode"], 400)
        self.events.update_item(Key={"eventId": "event"}, UpdateExpression="SET #src = :src", ExpressionAttributeNames={"#src": "source"}, ExpressionAttributeValues={":src": "ticketmaster"})
        self.assertEqual(producer.handler(self.request(), None)["statusCode"], 400)

    def test_idempotency_parameter_conflict_and_repeated_issuance(self):
        order = self.accept(); first = self.fulfill(order)
        self.assertEqual(self.accept(), order)
        self.assertEqual(producer.handler(self.request(2), None)["statusCode"], 409)
        for _ in range(3):
            flow.reserve(order); flow.pay(order); flow.issue(order)
        self.assertEqual(json.loads(self.lookup(order)["body"])["tickets"], first["tickets"])
        self.assertEqual(self.inventory()["sold"], 4)
        self.assertEqual(self.ddb.Table("tickets").scan()["Count"], 4)

    def test_payment_failure_releases_only_once(self):
        order = self.accept(); flow.reserve(order)
        self.assertEqual(self.inventory(), {"sold": 0, "reserved": 4, "available": 96})
        with self.assertRaises(flow.QuantityPaymentFailed): flow.pay({**order, "forceFail": True})
        for _ in range(2): flow.compensate({"order": order, "failureStage": "PAYMENT"})
        self.assertEqual(self.inventory(), {"sold": 0, "reserved": 0, "available": 100})
        with self.assertRaises(flow.QuantityPaymentFailed): flow.pay(order)

    def test_qr_failure_after_payment_retains_inventory_for_safe_recovery(self):
        order = self.accept(); flow.reserve(order); flow.pay(order)
        with patch.object(flow, "build_tickets", side_effect=RuntimeError("QR unavailable")):
            with self.assertRaises(RuntimeError): flow.issue(order)
        flow.compensate({"order": order, "failureStage": "FULFILLMENT"})
        self.assertEqual(json.loads(self.lookup(order)["body"])["orderStatus"], "REVIEW_REQUIRED")
        self.assertEqual(self.ddb.Table("tickets").scan()["Count"], 0)
        self.assertEqual(self.inventory(), {"sold": 0, "reserved": 4, "available": 96})
        flow.issue(order)
        self.assertEqual(self.inventory(), {"sold": 4, "reserved": 0, "available": 96})

    def test_lost_confirmation_response_and_late_compensation(self):
        order = self.accept(); flow.reserve(order); flow.pay(order)
        client = boto3.client("dynamodb"); real = client.transact_write_items
        def lost(**kwargs):
            real(**kwargs)
            raise TimeoutError("response lost")
        with patch.object(flow.boto3, "client", return_value=client), patch.object(client, "transact_write_items", side_effect=lost):
            with self.assertRaises(TimeoutError): flow.issue(order)
        flow.issue(order); flow.compensate({"order": order, "failureStage": "PAYMENT"})
        self.assertEqual(self.inventory(), {"sold": 4, "reserved": 0, "available": 96})

    def test_competing_preaccepted_orders_cannot_oversell(self):
        # Both requests pass intake before either atomic reservation occurs.
        self.events.update_item(Key={"eventId": "event"}, UpdateExpression="SET #cap = :q, available = :q", ExpressionAttributeNames={"#cap": "capacity"}, ExpressionAttributeValues={":q": 5})
        orders = [self.accept(user=user) for user in ("buyer-a", "buyer-b")]
        # Moto does not implement serializable threaded transactions. Serialize
        # its transaction calls, while allowing concurrent reads/workflow calls.
        client = boto3.client("dynamodb"); lock = threading.Lock(); real = client.transact_write_items
        def atomic(**kwargs):
            with lock: return real(**kwargs)
        def reserve(order):
            try:
                flow.reserve(order); return True
            except flow.InventoryUnavailable:
                flow.compensate({"order": {**order, "error": {"Error": "InventoryUnavailable"}}, "failureStage": "RESERVATION"})
                return False
        with patch.object(flow.boto3, "client", return_value=client), patch.object(client, "transact_write_items", side_effect=atomic):
            with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(reserve, orders))
        self.assertEqual(sorted(results), [False, True])
        winner = orders[results.index(True)]; flow.pay(winner); flow.issue(winner)
        self.assertEqual(self.inventory(), {"sold": 4, "reserved": 0, "available": 1})
        self.assertEqual(producer.handler(self.request(2, key="over"), None)["statusCode"], 409)

    def test_worker_preserves_quantity_schema_and_legacy_is_not_reinterpreted(self):
        order = self.accept()
        with patch.object(worker.boto3, "client") as client:
            client.return_value.start_execution.return_value = {"executionArn": "arn:execution"}
            result = worker.lambda_handler({"Records": [{"messageId": "m", "body": json.dumps(order)}]}, None)
            self.assertEqual(result, {"batchItemFailures": []})
            self.assertEqual(json.loads(client.return_value.start_execution.call_args.kwargs["input"])["quantity"], 4)
        legacy = {"body": json.dumps({"eventId": "event", "seatId": "4", "idempotencyKey": "old"}), **{k: v for k, v in self.request().items() if k != "body"}}
        self.assertEqual(producer.handler(legacy, None)["statusCode"], 409)

    def test_historical_ticket_and_migration_count(self):
        historical = {"orderId": "old-order", "userId": "old-user", "eventId": "legacy-event", "seatId": "4",
                      "orderStatus": "CONFIRMED", "ticketStatus": "issued", "paymentStatus": "paid", "qrPayload": "old-qr", "qrUrl": "old-url"}
        self.orders.put_item(Item=historical)
        self.assertEqual(json.loads(self.lookup(historical)["body"])["qrPayload"], "old-qr")
        events = [{"eventId": "legacy-event", "capacity": 10}]
        seats = [{"eventId": "legacy-event", "seatId": "4", "status": "sold", "heldBy": "old-order"}]
        plan = migration.migration_plan(events, [historical], seats)
        self.assertEqual(plan[0]["sold"], 1); self.assertEqual(plan[0]["available"], 9)
        for bad in ([{**historical, "orderStatus": "PENDING"}], [{**historical, "qrPayload": ""}]):
            with self.assertRaises(ValueError): migration.migration_plan(events, bad, seats)
        with self.assertRaises(ValueError): migration.migration_plan(events, [historical], [])
        self.assertEqual(migration.migration_plan([{**events[0], "inventoryVersion": 2}], [historical], seats), [])


if __name__ == "__main__":
    unittest.main()
