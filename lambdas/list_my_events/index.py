"""Sales summary for artists ("My events").

GET /my-events  (requires a Cognito login token, artist or admin group)
An artist gets only the events they created. An admin gets every event created
in our app. Imported Ticketmaster events are never included because they are
not sold here. Each event comes with capacity, sold, reserved, available and
revenue (sold tickets times the ticket price).
"""

import json
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr

_table = boto3.resource("dynamodb").Table(os.environ["EVENTS_TABLE"])

_FIELDS = ("eventId", "name", "artist", "city", "venue", "date", "genre", "price")


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _plain(value):
    # DynamoDB numbers come back as Decimal, which json cannot serialize.
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def handler(event, context):
    claims = (
        event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    )
    user_id = claims.get("sub")
    if not isinstance(user_id, str) or not user_id.strip():
        return _response(401, {"error": "Authentication required"})

    # HTTP API turns the group list into a string such as "[artist admin]".
    groups = str(claims.get("cognito:groups", "")).translate(
        str.maketrans({c: " " for c in "[],\"'"})
    ).split()
    is_admin = "admin" in groups
    if "artist" not in groups and not is_admin:
        return _response(403, {"error": "Only associations and admins can see sales"})

    condition = Attr("source").not_exists() | (
        Attr("source").ne("ticketmaster") & Attr("source").ne("barcelona_open_data")
    )
    if not is_admin:
        condition = condition & Attr("artistId").eq(user_id)

    items = []
    scan = {"FilterExpression": condition, "ConsistentRead": True}
    while True:
        page = _table.scan(**scan)
        items.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            break
        scan["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    events = []
    for item in items:
        capacity = int(item.get("capacity", 0))
        sold = int(item.get("sold", 0))
        reserved = int(item.get("reserved", 0))
        available = int(item.get("available", max(capacity - sold - reserved, 0)))
        price = item.get("price", 0)
        body = {f: _plain(item[f]) for f in _FIELDS if f in item}
        body.update(
            capacity=capacity,
            sold=sold,
            reserved=reserved,
            available=available,
            revenue=_plain(Decimal(str(price)) * sold),
            soldOut=capacity > 0 and available == 0,
        )
        events.append(body)

    events.sort(key=lambda e: str(e.get("date", "")))
    return _response(200, {"events": events})
