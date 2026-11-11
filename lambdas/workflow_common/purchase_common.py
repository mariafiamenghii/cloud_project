"""Shared workflow helpers, packaged into each workflow Lambda ZIP."""

import os
import re

import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError


class OrderMismatch(Exception):
    pass


class ConcurrentOrderChange(Exception):
    """Retry the operation against fresh state, never guess its outcome."""


def encode(values):
    return {key: TypeSerializer().serialize(value) for key, value in values.items()}


def read(client, table, key):
    item = client.get_item(TableName=table, Key=encode(key), ConsistentRead=True).get("Item")
    return {key: TypeDeserializer().deserialize(value) for key, value in item.items()} if item else None


def load_order(order):
    for field in ("orderId", "userId", "eventId", "seatId"):
        value = order.get(field)
        if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 128:
            raise OrderMismatch(f"Invalid {field}")
    if not re.fullmatch(r"[1-9][0-9]{0,9}", order["seatId"]):
        raise OrderMismatch("Noncanonical seatId")
    client = boto3.client("dynamodb")
    saved = read(client, os.environ["ORDERS_TABLE"], {"orderId": order["orderId"]})
    if not saved or any(saved.get(field) != order[field] for field in ("userId", "eventId", "seatId")):
        raise OrderMismatch("An existing matching Part C order is required")
    return client, saved


def identity(order):
    return (
        "attribute_exists(orderId) AND userId = :user AND eventId = :event AND seatId = :seat",
        {":user": order["userId"], ":event": order["eventId"], ":seat": order["seatId"]},
    )


def seat_key(order):
    return {"eventId": order["eventId"], "seatId": order["seatId"]}


def owned(seat, order):
    return bool(seat and seat.get("heldBy") == order["orderId"] and seat.get("heldForUser") == order["userId"])


def condition_failed(exc):
    if not isinstance(exc, ClientError):
        return False
    if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
        return True
    if exc.response["Error"]["Code"] != "TransactionCanceledException":
        return False
    # Throughput/conflict/validation failures must remain retryable errors, not
    # be mislabeled as an unavailable seat. DynamoDB includes cancellation reasons.
    reasons = [reason.get("Code", "None") for reason in exc.response.get("CancellationReasons", [])]
    return bool(reasons and "ConditionalCheckFailed" in reasons and
                all(code in ("None", "ConditionalCheckFailed") for code in reasons))


def ticket_result(order, saved):
    return {
        **order, "seatStatus": "sold", "ticketStatus": "issued",
        "qrPayload": saved["qrPayload"], "qrUrl": saved["qrUrl"],
        "issuedAt": int(saved["issuedAt"]),
    }


def save_email_status(client, order, status):
    condition, values = identity(order)
    try:
        client.update_item(
            TableName=os.environ["ORDERS_TABLE"], Key=encode({"orderId": order["orderId"]}),
            UpdateExpression="SET emailStatus = :status",
            ConditionExpression=(condition + " AND orderStatus = :confirmed AND ticketStatus = :issued"
                                 " AND (attribute_not_exists(emailStatus) OR emailStatus <> :sent)"),
            ExpressionAttributeValues=encode({**values, ":status": status, ":confirmed": "CONFIRMED",
                                               ":issued": "issued", ":sent": "sent"}),
        )
    except ClientError as exc:
        if not condition_failed(exc):
            raise
        _, saved = load_order(order)
        if saved.get("emailStatus") != "sent":
            raise ConcurrentOrderChange("Notification state changed") from exc
        return "sent"
    return status
