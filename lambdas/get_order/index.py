"""Read a single order's status and ticket, scoped to the authenticated owner.

Part D read side. Because SES is blocked on the Academy / Innovation Sandbox
accounts, the confirmation email cannot be delivered, so the website shows the
ticket (QR) instead. This route lets the frontend poll an order after the
asynchronous purchase workflow finishes and render its status and QR code.

GET /orders/{orderId}  (requires a Cognito login token)
Returns only the caller's own order. A caller can never read someone else's
purchase even if they guess the orderId.
"""

import json
import os
from decimal import Decimal

import boto3

_ddb = boto3.resource("dynamodb")

# Fields safe to expose to the buyer. We never leak internal bookkeeping such as
# the saved execution ARN or the request fingerprint.
_PUBLIC_FIELDS = (
    "orderId",
    "eventId",
    "seatId",
    "orderStatus",
    "ticketStatus",
    "paymentStatus",
    "emailStatus",
    "qrPayload",
    "qrUrl",
    "issuedAt",
    "failureStage",
    "quantity",
    "schemaVersion",
    "unitPrice",
    "totalPrice",
)


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

    order_id = (event.get("pathParameters") or {}).get("orderId")
    if not isinstance(order_id, str) or not order_id.strip() or len(order_id) > 256:
        return _response(400, {"error": "Missing or invalid orderId"})

    table = _ddb.Table(os.environ["ORDERS_TABLE"])
    item = table.get_item(Key={"orderId": order_id}, ConsistentRead=True).get("Item")

    # Same 404 whether the order is absent or owned by another user, so an
    # attacker cannot probe which order ids exist.
    if not item or item.get("userId") != user_id:
        return _response(404, {"error": "Order not found"})

    body = {field: _plain(item[field]) for field in _PUBLIC_FIELDS if field in item}
    if item.get("schemaVersion") == 2 and item.get("orderStatus") == "CONFIRMED":
        from boto3.dynamodb.conditions import Key
        tickets = _ddb.Table(os.environ["TICKETS_TABLE"]).query(
            KeyConditionExpression=Key("orderId").eq(order_id), ConsistentRead=True,
        )["Items"]
        if len(tickets) != item["quantity"]:
            return _response(503, {"error": "Ticket records require reconciliation"})
        public = ("ticketId", "qrPayload", "qrUrl", "issuedAt", "ticketNumber")
        body["tickets"] = [{k: _plain(t[k]) for k in public if k in t} for t in sorted(tickets, key=lambda t: t["ticketNumber"])]
    return _response(200, body)
