import json
import os
import time
import uuid
from decimal import Decimal

import boto3

table = boto3.resource("dynamodb").Table(os.environ["EVENTS_TABLE"])
REQUIRED = ["name", "city", "date", "price", "capacity"]


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event, context):
    # API Gateway already checked the token. Here we check the ROLE.
    claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    # HTTP API turns the group list into a string such as "[artist admin]".
    groups = str(claims.get("cognito:groups", "")).strip("[]").replace(",", " ").split()
    if "artist" not in groups and "admin" not in groups:
        return _response(403, {"error": "Only artists can create events"})

    try:
        data = json.loads(event.get("body") or "{}", parse_float=Decimal)
    except ValueError:
        return _response(400, {"error": "Body must be valid JSON"})

    missing = [f for f in REQUIRED if f not in data]
    if missing:
        return _response(400, {"error": "Missing fields: " + ", ".join(missing)})

    capacity, price = data["capacity"], data["price"]
    if (isinstance(capacity, bool) or not isinstance(capacity, (int, Decimal)) or capacity != int(capacity) or not 1 <= capacity <= 1000000
            or isinstance(price, bool) or not isinstance(price, (int, Decimal)) or not Decimal(price).is_finite() or price < 0):
        return _response(400, {"error": "Capacity must be a positive integer and price must be non-negative"})

    item = {
        "eventId": str(uuid.uuid4()),
        "artistId": claims["sub"],  # TODO later: edit/cancel only if artistId == caller
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
    # Optional fields used by the recommendations (genre, artist name, venue).
    for field in ("artist", "venue"):
        if str(data.get(field, "")).strip():
            item[field] = str(data[field]).strip()[:80]
    if str(data.get("genre", "")).strip():
        item["genre"] = str(data["genre"]).strip().lower()[:40]
    table.put_item(Item=item)
    return _response(201, {"eventId": item["eventId"]})
