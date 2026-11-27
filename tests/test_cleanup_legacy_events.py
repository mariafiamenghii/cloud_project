"""scripts/cleanup_legacy_events.py: report by default, delete only legacy events with --apply."""
import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import boto3
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cleanup_legacy_events as cleanup  # noqa: E402

EVENTS = [
    {"eventId": "tm-1", "source": "ticketmaster", "genre": "rock", "capacity": 0},
    {"eventId": "tm-2", "source": "ticketmaster", "genre": "pop", "capacity": 0},
    {"eventId": "old-sample", "source": "sample", "genre": "jazz", "capacity": 250},
    {"eventId": "new-sample", "source": "sample", "genre": "finance", "capacity": 120},
    {"eventId": "old-bcn", "source": "barcelona_open_data", "genre": "classical", "capacity": 0},
    {"eventId": "old-bcn-empty", "source": "barcelona_open_data", "genre": "", "capacity": 0},
    {"eventId": "new-bcn", "source": "barcelona_open_data", "genre": "music", "capacity": 0},
    {"eventId": "association", "genre": "rock", "capacity": 50},
    {"eventId": "association-internal", "source": "internal", "genre": "jazz", "capacity": 50},
    {"eventId": "unknown-source", "source": "eventbrite", "genre": "rock", "capacity": 0},
    {"eventId": "tm-with-order", "source": "ticketmaster", "genre": "rock", "capacity": 0},
    {"eventId": "sample-sold", "source": "sample", "genre": "indie", "capacity": 10, "sold": 1},
    {"eventId": "sample-reserved", "source": "sample", "genre": "indie", "capacity": 10, "reserved": 2},
    {"eventId": "sample-seat", "source": "sample", "genre": "latin", "capacity": 10},
]
DELETED = {"tm-1", "tm-2", "old-sample", "old-bcn", "old-bcn-empty"}


class CleanupLegacyEventsTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {
            "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
            "AWS_DEFAULT_REGION": "us-east-1", "AWS_EC2_METADATA_DISABLED": "true",
        }, clear=True)
        env.start()
        self.addCleanup(env.stop)
        aws = mock_aws()
        aws.start()
        self.addCleanup(aws.stop)
        ddb = boto3.resource("dynamodb", region_name="us-east-1")

        def table(name, *keys):
            return ddb.create_table(
                TableName=name, BillingMode="PAY_PER_REQUEST",
                KeySchema=[{"AttributeName": k, "KeyType": t} for k, t in zip(keys, ("HASH", "RANGE"))],
                AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k in keys])

        self.events = table("ticketing-events", "eventId")
        self.orders = table("ticketing-orders", "orderId")
        self.seats = table("ticketing-seats", "eventId", "seatId")
        for event in EVENTS:
            self.events.put_item(Item=event)
        self.orders.put_item(Item={"orderId": "purchase-1", "eventId": "tm-with-order", "orderStatus": "REJECTED"})
        self.seats.put_item(Item={"eventId": "sample-seat", "seatId": "1", "status": "sold"})

    def run_script(self, *args):
        out = io.StringIO()
        with patch.object(sys, "argv", ["cleanup_legacy_events.py", *args]), contextlib.redirect_stdout(out):
            cleanup.main()
        return out.getvalue()

    def remaining(self):
        return {item["eventId"] for item in self.events.scan()["Items"]}

    def test_default_run_only_reports(self):
        output = self.run_script()
        self.assertEqual(self.remaining(), {e["eventId"] for e in EVENTS})
        self.assertIn("Legacy events to delete: 5", output)
        self.assertIn("ticketmaster: 2", output)
        self.assertIn("sample: 1", output)
        self.assertIn("barcelona_open_data: 2", output)
        self.assertIn("jazz: 1", output)
        self.assertIn("(none): 1", output)
        self.assertIn("Nothing was deleted", output)

    def test_apply_deletes_only_legacy_events_without_sales(self):
        output = self.run_script("--apply")
        self.assertEqual(self.remaining(), {e["eventId"] for e in EVENTS} - DELETED)
        self.assertIn("Deleted 5 events", output)
        # Orders and seats are never touched.
        self.assertEqual(self.orders.scan()["Count"], 1)
        self.assertEqual(self.seats.scan()["Count"], 1)

    def test_events_with_orders_seats_or_tickets_are_kept_with_a_reason(self):
        output = self.run_script()
        self.assertIn("Legacy events kept for safety: 4", output)
        self.assertIn("tm-with-order (ticketmaster, ): has orders", output)
        self.assertIn("sample-sold (sample, ): has sold or reserved tickets", output)
        self.assertIn("sample-reserved (sample, ): has sold or reserved tickets", output)
        self.assertIn("sample-seat (sample, ): has seat records", output)
        self.assertIn("Events with an unknown source (never deleted): {'eventbrite': 1}", output)

    def test_association_and_current_events_are_never_legacy(self):
        for event in EVENTS:
            if event["eventId"] in ("association", "association-internal", "new-sample", "new-bcn", "unknown-source"):
                self.assertFalse(cleanup.is_legacy(event), event["eventId"])

    def test_event_that_gets_a_sale_after_the_scan_is_not_deleted(self):
        delete, _ = cleanup.plan(cleanup.scan(self.events), [], self.seats)
        self.events.update_item(Key={"eventId": "old-sample"}, UpdateExpression="SET sold = :one",
                                ExpressionAttributeValues={":one": 1})
        deleted = {e["eventId"] for e in delete if cleanup.delete_event(self.events, e)}
        self.assertNotIn("old-sample", deleted)
        self.assertIn("old-sample", self.remaining())


if __name__ == "__main__":
    unittest.main()
