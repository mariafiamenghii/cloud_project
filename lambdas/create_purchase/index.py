"""Authenticated HTTP API v2 purchase intake; fulfillment is asynchronous."""

import base64
import hashlib
import json
import logging
import os
import re
from decimal import Decimal

import boto3

logger = logging.getLogger(__name__)


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event, context):
    claims = (
        event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    )
    user_id = claims.get("sub")
    if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 128:
        return _response(401, {"error": "Authentication required"})

    try:
        body = event.get("body") or ""
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body, validate=True).decode("utf-8")
        if len(body.encode("utf-8")) > 4096:
            raise ValueError("Body too large")
        data = json.loads(body)
        if not isinstance(data, dict) or set(data) != {"eventId", "seatId", "idempotencyKey"}:
            raise ValueError("Supply only eventId, seatId and idempotencyKey")
        event_id = data["eventId"]
        seat_id = data["seatId"]
        key = data["idempotencyKey"]
        if (
            not isinstance(event_id, str)
            or not event_id.strip()
            or event_id != event_id.strip()
            or len(event_id) > 128
        ):
            raise ValueError("Invalid eventId")
        if not isinstance(seat_id, str) or not re.fullmatch(r"[1-9][0-9]{0,9}", seat_id):
            raise ValueError("seatId must be a canonical positive integer string")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", key):
            raise ValueError("Invalid idempotencyKey")
    except (ValueError, TypeError, UnicodeError):
        return _response(
            400, {"error": "Invalid purchase: use eventId, numeric seatId and idempotencyKey"}
        )

    # Scope the caller's key to their authenticated identity, not to the payload.
    # Changing a purchase under the same key must conflict rather than create a new order.
    identity = json.dumps([user_id, key], separators=(",", ":"), ensure_ascii=True)
    order_id = "purchase-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
    order = {"orderId": order_id, "userId": user_id, "eventId": event_id, "seatId": seat_id}

    try:
        ddb = boto3.resource("dynamodb")
        existing = ddb.Table(os.environ["ORDERS_TABLE"]).get_item(
            Key={"orderId": order_id}, ConsistentRead=True
        ).get("Item")
        if existing:
            if any(existing.get(field) != value for field, value in order.items()):
                return _response(409, {"error": "Idempotency key already used for another purchase"})
            if existing.get("dispatchStatus") == "STARTED":
                return _response(202, {"orderId": order_id, "status": "accepted"})
        else:
            item = ddb.Table(os.environ["EVENTS_TABLE"]).get_item(
                Key={"eventId": event_id}, ConsistentRead=True
            ).get("Item")
            if not item:
                return _response(404, {"error": "Event not found"})
            capacity = item.get("capacity")
            if (
                isinstance(capacity, bool)
                or not isinstance(capacity, (int, Decimal))
                or (isinstance(capacity, Decimal) and not capacity.is_finite())
                or capacity <= 0
                or capacity != int(capacity)
                or int(seat_id) > capacity
                or item.get("source") == "ticketmaster"
            ):
                return _response(400, {"error": "Event or seat is not available for purchase"})

        boto3.client("sqs").send_message(
            QueueUrl=os.environ["PURCHASE_QUEUE_URL"],
            MessageBody=json.dumps(order, sort_keys=True, separators=(",", ":")),
        )
    except Exception as exc:
        logger.error("Purchase intake failed for %s (%s)", order_id, type(exc).__name__)
        return _response(
            503, {"error": "Purchase temporarily unavailable; retry with the same idempotencyKey"}
        )

    return _response(202, {"orderId": order_id, "status": "accepted"})
