"""List the authenticated buyer's own orders and tickets ("My tickets").

GET /orders  (requires a Cognito login token)
Returns the caller's most recent orders, newest first, each with the event
name and, for confirmed orders, the ticket QR codes. The user id always comes
from the token, so nobody can list another person's orders.
"""

import json
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

_ddb = boto3.resource("dynamodb")

MAX_ORDERS = 20

_PUBLIC_FIELDS = (
    "orderId",
    "eventId",
    "seatId",
    "orderStatus",
    "ticketStatus",
    "paymentStatus",
    "qrPayload",
    "qrUrl",
    "issuedAt",
    "quantity",
    "schemaVersion",
    "unitPrice",
    "totalPrice",
)

_TICKET_FIELDS = ("ticketId", "qrPayload", "qrUrl", "issuedAt", "ticketNumber")


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

    orders_table = _ddb.Table(os.environ["ORDERS_TABLE"])
    tickets_table = _ddb.Table(os.environ["TICKETS_TABLE"])
    events_table = _ddb.Table(os.environ["EVENTS_TABLE"])

    items = []
    query = {"IndexName": "by-user", "KeyConditionExpression": Key("userId").eq(user_id)}
    while True:
        page = orders_table.query(**query)
        items.extend(page["Items"])
        if "LastEvaluatedKey" not in page or len(items) >= 200:
            break
        query["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    # Newest first. Orders that never got a ticket have no issuedAt and go last.
    items.sort(key=lambda i: str(i.get("issuedAt", "")), reverse=True)
    items = items[:MAX_ORDERS]

    titles = {}
    orders = []
    for item in items:
        body = {f: _plain(item[f]) for f in _PUBLIC_FIELDS if f in item}

        event_id = item.get("eventId")
        if event_id and event_id not in titles:
            found = events_table.get_item(Key={"eventId": event_id}).get("Item") or {}
            titles[event_id] = {
                k: _plain(found[k]) for k in ("name", "artist", "city", "date", "venue") if k in found
            }
        body["event"] = titles.get(event_id, {})

        if item.get("schemaVersion") == 2 and item.get("orderStatus") == "CONFIRMED":
            rows = tickets_table.query(
                KeyConditionExpression=Key("orderId").eq(item["orderId"]), ConsistentRead=True
            )["Items"]
            rows.sort(key=lambda t: t.get("ticketNumber", 0))
            body["tickets"] = [{k: _plain(t[k]) for k in _TICKET_FIELDS if k in t} for t in rows]
        orders.append(body)

    return _response(200, {"orders": orders})
