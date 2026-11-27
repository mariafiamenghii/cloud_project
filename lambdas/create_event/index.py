import json
import os
import time
import uuid
from decimal import Decimal

import boto3

from categories import CATEGORIES

table = boto3.resource("dynamodb").Table(os.environ["EVENTS_TABLE"])
REQUIRED = ["name", "city", "date", "price", "capacity"]
MAX_DESCRIPTION = 300


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event, context):
    # API Gateway already checked the token. Here we check the ROLE.
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not isinstance(claims.get("sub"), str) or not claims["sub"].strip():
        return _response(401, {"error": "Authentication required"})
    # HTTP API turns the group list into a string such as "[artist admin]".
    groups = str(claims.get("cognito:groups", "")).translate(str.maketrans({c: " " for c in "[],\"'"})).split()
    if "artist" not in groups and "admin" not in groups:
        return _response(403, {"error": "Only associations can create events"})

    try:
        data = json.loads(event.get("body") or "{}", parse_float=Decimal)
    except ValueError:
        return _response(400, {"error": "Body must be valid JSON"})
    if not isinstance(data, dict) or "imageUrl" in data or "imageObjectKey" in data:
        return _response(400, {"error": "Use an authorized image upload reference"})

    missing = [f for f in REQUIRED if f not in data]
    if missing:
        return _response(400, {"error": "Missing fields: " + ", ".join(missing)})

    capacity, price = data["capacity"], data["price"]
    if (isinstance(capacity, bool) or not isinstance(capacity, (int, Decimal)) or capacity != int(capacity) or not 1 <= capacity <= 1000000
            or isinstance(price, bool) or not isinstance(price, (int, Decimal)) or not Decimal(price).is_finite() or price < 0):
        return _response(400, {"error": "Capacity must be a positive integer and price must be non-negative"})

    # The category is stored in the "genre" field (kept for compatibility).
    # It is optional for API callers, but if given it must be one of CATEGORIES.
    raw_category = data.get("genre", "")
    category = raw_category.strip().lower() if isinstance(raw_category, str) else None
    if category is None or (category and category not in CATEGORIES):
        return _response(400, {"error": "Category must be one of: " + ", ".join(CATEGORIES)})

    # Optional short description shown on the event card and the purchase page.
    description = data.get("description", "")
    if not isinstance(description, str) or len(description.strip()) > MAX_DESCRIPTION:
        return _response(400, {"error": f"Description must be text of at most {MAX_DESCRIPTION} characters"})

    item = {
        "eventId": str(uuid.uuid4()),
        "artistId": claims["sub"],  # the publishing association; delete_event checks it
        "name": data["name"],
        "city": data["city"],
        "date": data["date"],
        "price": data["price"],
        "capacity": int(data["capacity"]),
        "createdAt": int(time.time()),
        "inventoryVersion": 2,
        "sold": 0,
        "reserved": 0,
        "available": int(capacity),
    }
    # Optional fields used by the recommendations ("artist" = association or
    # club name, venue, and the category validated above).
    for field in ("artist", "venue"):
        if str(data.get(field, "")).strip():
            item[field] = str(data[field]).strip()[:80]
    if category:
        item["genre"] = category
    if description.strip():
        item["description"] = description.strip()
    published = None
    image_key = data.get("imageKey")
    if image_key is not None and image_key != "":
        from image_validation import publish_image, discard
        try:
            published = publish_image(image_key, claims["sub"], item["eventId"])
        except ValueError as error:
            return _response(400, {"error": str(error)})
        item["imageObjectKey"] = published
        item["imageUrl"] = os.environ["PUBLIC_API_URL"] + "/event-images/" + item["eventId"]
    try:
        table.put_item(Item=item)
    except Exception:
        if published: discard(published)
        raise
    if published: discard(image_key)
    return _response(201, {"eventId": item["eventId"]})
