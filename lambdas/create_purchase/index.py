"""Authenticated HTTP API v2 purchase intake; fulfillment is asynchronous."""

import base64
import hashlib
import json
import logging
import os
import re
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

from purchase_dispatch import persist_pending_order, read_order, serialize_order

logger = logging.getLogger(__name__)


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def legacy_handler(event, context):
    claims = (
        event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    )
    user_id = claims.get("sub")
    if (
        not isinstance(user_id, str)
        or not user_id.strip()
        or user_id != user_id.strip()
        or len(user_id) > 128
    ):
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
    workflow_input = serialize_order(order)
    accepted = {"orderId": order_id, "status": "accepted"}

    try:
        ddb = boto3.resource("dynamodb")
        orders = ddb.Table(os.environ["ORDERS_TABLE"])
        existing = read_order(orders, order_id)
        if existing is None:
            item = ddb.Table(os.environ["EVENTS_TABLE"]).get_item(
                Key={"eventId": event_id}, ConsistentRead=True
            ).get("Item")
            if not item:
                return _response(404, {"error": "Event not found"})
            if item.get("inventoryVersion") == 2:
                return _response(409, {"error": "This event uses ticket quantities. Refresh the purchase page."})
            capacity = item.get("capacity")
            if (
                isinstance(capacity, bool)
                or not isinstance(capacity, (int, Decimal))
                or (isinstance(capacity, Decimal) and not capacity.is_finite())
                or capacity <= 0
                or capacity != int(capacity)
                or int(seat_id) > capacity
                or item.get("source") in ("ticketmaster", "barcelona_open_data")
            ):
                return _response(400, {"error": "Event or seat is not available for purchase"})
            existing = persist_pending_order(orders, order, workflow_input)

        if any(existing.get(field) != value for field, value in order.items()):
            return _response(409, {"error": "Idempotency key already used for another purchase"})
        if existing.get("dispatchStatus") == "STARTED":
            return _response(202, accepted)

        # If SQS fails, leave the pending order in place. Retrying with the same
        # key reuses it and can resend the identical message safely.
        boto3.client("sqs").send_message(
            QueueUrl=os.environ["PURCHASE_QUEUE_URL"],
            MessageBody=workflow_input,
        )
    except Exception as exc:
        error = exc.response["Error"]["Code"] if isinstance(exc, ClientError) else type(exc).__name__
        logger.error("Purchase intake failed for %s (%s)", order_id, error)
        return _response(
            503, {"error": "Purchase temporarily unavailable; retry with the same idempotencyKey"}
        )

    return _response(202, accepted)


def handler(event, context):
    if os.environ.get("PURCHASES_ENABLED", "true") != "true":
        return _response(503, {"error": "Purchases are temporarily paused for an inventory upgrade"})
    try:
        raw = event.get("body") or ""
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw, validate=True).decode("utf-8")
        data = json.loads(raw)
    except (ValueError, TypeError, UnicodeError):
        return legacy_handler(event, context)
    if not isinstance(data, dict) or "quantity" not in data:
        return legacy_handler(event, context)
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    user = claims.get("sub")
    if not isinstance(user, str) or not user.strip() or user != user.strip() or len(user) > 128:
        return _response(401, {"error": "Authentication required"})
    q, event_id, key = data.get("quantity"), data.get("eventId"), data.get("idempotencyKey")
    if (len(raw.encode()) > 4096 or set(data) != {"eventId", "quantity", "idempotencyKey"}
            or type(q) is not int or not 1 <= q <= 20
            or not isinstance(event_id, str) or not event_id.strip() or event_id != event_id.strip() or len(event_id) > 128
            or not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", key)):
        return _response(400, {"error": "Supply eventId, integer quantity (1–20), and idempotencyKey"})
    identity = json.dumps([user, key], separators=(",", ":"), ensure_ascii=True)
    order_id = "purchase-" + hashlib.sha256(identity.encode()).hexdigest()
    order = {"orderId": order_id, "userId": user, "eventId": event_id, "quantity": q, "schemaVersion": 2}
    workflow_input = serialize_order(order)
    try:
        ddb = boto3.resource("dynamodb")
        orders = ddb.Table(os.environ["ORDERS_TABLE"])
        existing = read_order(orders, order_id)
        if existing is None:
            item = ddb.Table(os.environ["EVENTS_TABLE"]).get_item(Key={"eventId": event_id}, ConsistentRead=True).get("Item")
            if not item:
                return _response(404, {"error": "Event not found"})
            if item.get("source") in ("ticketmaster", "barcelona_open_data"):
                return _response(400, {"error": "Use the external ticket provider"})
            if item.get("inventoryVersion") != 2:
                return _response(503, {"error": "Event inventory is awaiting migration"})
            if item.get("available", 0) < q:
                return _response(409, {"error": "Not enough tickets remaining"})
            existing = persist_pending_order(orders, order, workflow_input)
        if any(existing.get(k) != v for k, v in order.items()):
            return _response(409, {"error": "Idempotency key already used for another purchase"})
        if existing.get("dispatchStatus") != "STARTED":
            boto3.client("sqs").send_message(QueueUrl=os.environ["PURCHASE_QUEUE_URL"], MessageBody=workflow_input)
        return _response(202, {"orderId": order_id, "status": "accepted"})
    except Exception as exc:
        code = exc.response["Error"]["Code"] if isinstance(exc, ClientError) else type(exc).__name__
        logger.error("Quantity intake failed for %s (%s)", order_id, code)
        return _response(503, {"error": "Purchase temporarily unavailable; retry with the same idempotencyKey"})
