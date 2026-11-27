"""Event categories: one list on the web, one in the create_event Lambda.

The parity test fails if web/src/utils/eventMedia.ts (CATEGORIES) and
lambdas/create_event/categories.py (CATEGORIES) stop matching.
"""
import importlib.util
import json
import os
import re
import sys
import unittest
from unittest.mock import patch

import boto3
from moto import mock_aws

from test_purchases import ROOT, load_lambda

CATEGORIES_PY = ROOT / "lambdas/create_event/categories.py"
EVENT_MEDIA_TS = ROOT / "web/src/utils/eventMedia.ts"


def backend_categories():
    spec = importlib.util.spec_from_file_location("event_categories", CATEGORIES_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.CATEGORIES)


def web_categories():
    source = EVENT_MEDIA_TS.read_text(encoding="utf-8")
    block = re.search(r"export const CATEGORIES\s*=\s*\[(.*?)\];", source, re.S)
    assert block, "CATEGORIES array not found in eventMedia.ts"
    body = re.sub(r"//[^\n]*", "", block.group(1))  # ignore comments inside the array
    return re.findall(r'"([^"]+)"', body)


class CategoryParityTests(unittest.TestCase):
    def test_web_and_lambda_lists_are_identical(self):
        web = [c.lower() for c in web_categories()]
        self.assertEqual(web, backend_categories(),
                         "Update eventMedia.ts and create_event/categories.py together")

    def test_stored_values_are_unique_lowercase_words(self):
        values = backend_categories()
        self.assertEqual(len(values), len(set(values)))
        for value in values:
            self.assertRegex(value, r"^[a-z]+$")

    def test_sample_events_use_shared_categories_and_can_be_sold(self):
        events = json.loads((ROOT / "data/sample_events.json").read_text(encoding="utf-8"))
        self.assertGreater(len(events), 0)
        keys = set()
        for event in events:
            self.assertIn(event["genre"], backend_categories(), event["name"])
            self.assertGreater(event["capacity"], 0, event["name"])
            keys.add((event["artist"], event["date"], event["venue"]))  # load_events.py id
        self.assertEqual(len(keys), len(events), "two sample events would share an eventId")


class CreateEventCategoryTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {
            "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
            "AWS_DEFAULT_REGION": "us-east-1", "AWS_EC2_METADATA_DISABLED": "true",
            "EVENTS_TABLE": "events",
        }, clear=True)
        env.start()
        self.addCleanup(env.stop)
        aws = mock_aws()
        aws.start()
        self.addCleanup(aws.stop)
        self.table = boto3.resource("dynamodb").create_table(
            TableName="events", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "eventId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "eventId", "AttributeType": "S"}])
        path = patch.object(sys, "path", [str(ROOT / "lambdas/create_event"), *sys.path])
        path.start()
        self.addCleanup(path.stop)
        self.creator = load_lambda("create_event")

    def create(self, **extra):
        body = {"name": "Finance Club Networking Night", "city": "Barcelona",
                "date": "2026-12-20", "price": 10, "capacity": 50, **extra}
        claims = {"sub": "association-a", "cognito:groups": "[artist]"}
        return self.creator.handler(
            {"body": json.dumps(body), "requestContext": {"authorizer": {"jwt": {"claims": claims}}}}, None)

    def stored(self, response):
        event_id = json.loads(response["body"])["eventId"]
        return self.table.get_item(Key={"eventId": event_id})["Item"]

    def test_allowed_category_is_stored_lowercase(self):
        response = self.create(genre=" Finance ")
        self.assertEqual(response["statusCode"], 201, response)
        self.assertEqual(self.stored(response)["genre"], "finance")

    def test_unknown_category_is_rejected(self):
        for bad in ("rock", "jazz", "Free text up to forty characters", 42, ["finance"]):
            response = self.create(genre=bad)
            self.assertEqual(response["statusCode"], 400, bad)
            self.assertIn("Category must be one of", json.loads(response["body"])["error"])
        self.assertEqual(self.table.scan()["Count"], 0)

    def test_missing_category_is_allowed_for_api_callers(self):
        response = self.create()
        self.assertEqual(response["statusCode"], 201, response)
        self.assertNotIn("genre", self.stored(response))

    def test_fans_get_association_wording(self):
        body = {"name": "x", "city": "Barcelona", "date": "2026-12-20", "price": 1, "capacity": 1}
        claims = {"sub": "fan-a", "cognito:groups": "[fan]"}
        response = self.creator.handler(
            {"body": json.dumps(body), "requestContext": {"authorizer": {"jwt": {"claims": claims}}}}, None)
        self.assertEqual(response["statusCode"], 403)
        self.assertIn("associations", json.loads(response["body"])["error"])


if __name__ == "__main__":
    unittest.main()
