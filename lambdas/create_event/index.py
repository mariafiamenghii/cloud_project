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
    if "artist" not in groups:
        return _response(403, {"error": "Only artists can create events"})

    try:
        data = json.loads(event.get("body") or "{}", parse_float=Decimal)
    except ValueError:
        return _response(400, {"error": "Body must be valid JSON"})

    missing = [f for f in REQUIRED if f not in data]
    if missing:
        return _response(400, {"error": "Missing fields: " + ", ".join(missing)})

    item = {
        "eventId": str(uuid.uuid4()),
        "artistId": claims["sub"],  # TODO later: edit/cancel only if artistId == caller
        "name": data["name"],
        "city": data["city"],
        "date": data["date"],
        "price": data["price"],
        "capacity": int(data["capacity"]),
        "createdAt": int(time.time()),
    }
    table.put_item(Item=item)
    return _response(201, {"eventId": item["eventId"]})
