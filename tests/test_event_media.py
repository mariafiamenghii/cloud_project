import base64
import importlib.util
import io
import json
import os
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

import boto3
from botocore.exceptions import ClientError
from moto import mock_aws
from PIL import Image
from test_purchases import ROOT, load_lambda

sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "lambdas/create_event"))
from ticketmaster_media import metadata, safe_update, Discovery
import image_validation

spec = importlib.util.spec_from_file_location("tm_import", ROOT / "scripts/import_ticketmaster.py")
tm_import = importlib.util.module_from_spec(spec); spec.loader.exec_module(tm_import)


class MetadataTests(unittest.TestCase):
    def test_landscape_nonfallback_resolution_and_attribution(self):
        images = [
            {"url": "https://images.example/fallback", "width": 1920, "height": 1080, "fallback": True},
            {"url": "https://images.example/square", "width": 1920, "height": 1920},
            {"url": "https://images.example/small", "width": 640, "height": 360},
            {"url": "https://images.example/large", "width": 1280, "height": 720, "attribution": "Photographer credit"},
        ]
        result = metadata({"images": images, "priceRanges": [{"currency": "EUR", "min": 25}]})
        self.assertEqual(result["imageUrl"], images[3]["url"])
        self.assertEqual(result["imageAttribution"], "Photographer credit")
        self.assertEqual((result["price"], result["currency"]), (25, "EUR"))

    def test_lowest_price_within_currency_and_missing_values(self):
        result = metadata({"priceRanges": [{"currency": "USD", "min": 1}, {"currency": "EUR", "min": 40},
            {"currency": "EUR", "min": 25}, {"currency": "EUR", "min": -1}, {"currency": "EUR", "min": "NaN"}]})
        self.assertEqual(result, {"price": Decimal(25), "currency": "EUR"})
        self.assertEqual(metadata({}), {})
        self.assertNotIn("price", metadata({"images": [{"url": "https://image.example/a"}]}))
        self.assertEqual(metadata({"priceRanges": [{"currency": "USD", "min": 12}]})["currency"], "USD")

    def test_event_details_then_official_image_endpoint(self):
        client = Discovery("test-key")
        with patch.object(client, "get", side_effect=[{"priceRanges": [{"currency": "EUR", "min": 30}]}, {"images": [{"url": "https://image.example/event"}]}]) as get:
            result = metadata(client.enrich({"id": "official-id"}))
        self.assertEqual(result["price"], 30)
        self.assertEqual(get.call_args_list[1].args[0], "events/official-id/images.json")

    def test_converter_preserves_external_link_and_identity(self):
        event = {"id": "tm-id", "name": "Concert", "dates": {"start": {"localDate": "2026-12-20"}},
                 "url": "https://ticketmaster.es/event/123", "images": [{"url": "https://image.example/concert"}]}
        first = tm_import.convert(event); second = tm_import.convert(event)
        self.assertEqual(first["eventId"], second["eventId"])
        self.assertEqual(first["source"], "ticketmaster")
        self.assertEqual(first["externalUrl"], event["url"])
        self.assertEqual(first["imageUrl"], event["images"][0]["url"])


class UploadTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
            "AWS_DEFAULT_REGION": "us-east-1", "AWS_EC2_METADATA_DISABLED": "true", "EVENTS_TABLE": "events",
            "IMAGES_BUCKET": "event-test-images", "PUBLIC_API_URL": "https://api.example"}, clear=True)
        env.start(); self.addCleanup(env.stop)
        aws = mock_aws(); aws.start(); self.addCleanup(aws.stop)
        self.s3 = boto3.client("s3"); self.s3.create_bucket(Bucket="event-test-images")
        self.table = boto3.resource("dynamodb").create_table(TableName="events", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "eventId", "KeyType": "HASH"}], AttributeDefinitions=[{"AttributeName": "eventId", "AttributeType": "S"}])
        self.images = load_lambda("event_images"); self.creator = load_lambda("create_event")

    def auth(self, body, user="artist-a", groups="[artist]"):
        return {"body": json.dumps(body), "requestContext": {"authorizer": {"jwt": {"claims": {"sub": user, "cognito:groups": groups}}}}}

    def authorization(self, mime="image/png", size=100):
        result = self.images.handler(self.auth({"contentType": mime, "size": size}), None)
        self.assertEqual(result["statusCode"], 200, result)
        return json.loads(result["body"])

    def upload(self, fmt="PNG", declared=None):
        output = io.BytesIO(); Image.new("RGB", (120, 80), "purple").save(output, format=fmt)
        content = output.getvalue(); mime = declared or {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[fmt]
        key = self.authorization(mime, len(content))["key"]
        self.s3.put_object(Bucket="event-test-images", Key=key, Body=content, ContentType=mime)
        return key

    def create(self, key=None, user="artist-a", **extra):
        data = {"name": "Catalan image event", "city": "Barcelona", "date": "2026-12-20", "genre": "catalan", "price": 25, "capacity": 100, **extra}
        if key is not None: data["imageKey"] = key
        return self.creator.handler(self.auth(data, user), None)

    def test_jpeg_png_webp_publish_and_stable_serving(self):
        for fmt in ("JPEG", "PNG", "WEBP"):
            result = self.create(self.upload(fmt)); self.assertEqual(result["statusCode"], 201, result)
            event_id = json.loads(result["body"])["eventId"]
            item = self.table.get_item(Key={"eventId": event_id})["Item"]
            self.assertEqual((item["available"], item["sold"], item["reserved"]), (100, 0, 0))
            self.assertEqual(item["genre"], "catalan")
            self.assertEqual(item["imageUrl"], "https://api.example/event-images/" + event_id)
            for _ in range(2):
                response = self.images.handler({"pathParameters": {"eventId": event_id}}, None)
                self.assertEqual(response["statusCode"], 200)
                with Image.open(io.BytesIO(base64.b64decode(response["body"]))) as image: self.assertEqual(image.format, "WEBP")

    def test_auth_and_size_type_limits(self):
        data = {"contentType": "image/png", "size": 100}
        for user, group, expected in (("", "[artist]", 401), ("fan", "[fan]", 403)):
            self.assertEqual(self.images.handler(self.auth(data, user, group), None)["statusCode"], expected)
        for data in ({"contentType": "image/svg+xml", "size": 20}, {"contentType": "image/png", "size": 5242881}, {"contentType": "image/png", "size": 0}):
            self.assertEqual(self.images.handler(self.auth(data), None)["statusCode"], 400)
        authorization = self.authorization()
        policy = json.loads(base64.b64decode(authorization["fields"]["policy"]))
        self.assertIn(["content-length-range", 1, 5242880], policy["conditions"])
        self.assertTrue(authorization["key"].startswith("uploads/artist-a/"))

    def test_bad_actual_content_mime_and_owner_are_rejected(self):
        key = self.upload()
        self.assertEqual(self.create(key, user="artist-b")["statusCode"], 400)
        self.assertEqual(self.create(imageUrl="https://arbitrary.example/image")["statusCode"], 400)
        self.assertEqual(self.create(self.upload("JPEG", "image/png"))["statusCode"], 400)
        self.s3.put_object(Bucket="event-test-images", Key=key, Body=b"not-an-image", ContentType="image/png")
        self.assertEqual(self.create(key)["statusCode"], 400)
        self.s3.put_object(Bucket="event-test-images", Key=key, Body=b"x" * 5242881, ContentType="image/png")
        self.assertEqual(self.create(key)["statusCode"], 400)

    def test_optional_image_and_failed_upload_recovery(self):
        self.assertEqual(self.create()["statusCode"], 201)
        key = self.authorization()["key"]
        self.assertEqual(self.create(key)["statusCode"], 400)
        output = io.BytesIO(); Image.new("RGB", (10, 10)).save(output, format="PNG")
        self.s3.put_object(Bucket="event-test-images", Key=key, Body=output.getvalue(), ContentType="image/png")
        self.assertEqual(self.create(key)["statusCode"], 201)
        self.assertEqual(self.images.handler({"pathParameters": {"eventId": "unassociated"}}, None)["statusCode"], 404)

    def test_failed_event_write_does_not_expose_or_leave_published_object(self):
        key = self.upload()
        with patch.object(self.creator.table, "put_item", side_effect=RuntimeError("database failure")):
            with self.assertRaises(RuntimeError): self.create(key)
        self.assertEqual(self.s3.list_objects_v2(Bucket="event-test-images", Prefix="published/").get("KeyCount"), 0)
        self.assertIsNotNone(self.s3.get_object(Bucket="event-test-images", Key=key))

    def test_backfill_is_metadata_only_preserves_price_inventory_and_link(self):
        original = {"eventId": "tm", "source": "ticketmaster", "externalUrl": "https://ticketmaster.es/123", "capacity": 100,
                    "available": 90, "sold": 8, "reserved": 2, "inventoryVersion": 2, "price": Decimal(25), "currency": "EUR"}
        self.table.put_item(Item=original)
        updates = metadata({"images": [{"url": "https://image.example/new"}]})
        safe_update(self.table, original, updates)
        current = self.table.get_item(Key={"eventId": "tm"})["Item"]
        self.assertEqual({k: current[k] for k in original}, original)
        with self.assertRaises(AssertionError): safe_update(self.table, current, {"available": 0})
        self.table.put_item(Item={"eventId": "native", "source": "internal"})
        with self.assertRaises(ClientError): safe_update(self.table, {"eventId": "native"}, updates)

    def test_catalan_recommendation_matches_saved_preference(self):
        recommend = load_lambda("recommend")
        score, reasons = recommend.score_event({"genre": "catalan"}, {"genres": ["catalan"]})
        self.assertEqual(score, 3); self.assertIn("you like catalan", reasons)
