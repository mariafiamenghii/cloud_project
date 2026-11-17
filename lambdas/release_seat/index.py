"""Record failures; release only this order's unpaid hold, atomically."""

import os
import time

from botocore.exceptions import ClientError
from purchase_common import (
    ConcurrentOrderChange, condition_failed, encode, identity, load_order,
    owned, read, save_email_status, seat_key,
)


def handler(event, context):
    # Retain raw-order compatibility for controlled compensation tests.
    order = event.get("order", event)
    stage = event.get("failureStage", "PAYMENT")
    client, saved = load_order(order)
    if stage == "NOTIFICATION":
        status = save_email_status(client, order, "not_sent")
        return {"orderId": order["orderId"], "emailStatus": status}
    if saved.get("ticketStatus") == "issued" or saved.get("orderStatus") in (
        "FAILED", "REJECTED", "REVIEW_REQUIRED"
    ):
        return {"orderId": order["orderId"], "orderStatus": saved["orderStatus"], "released": False}

    paid = saved.get("paymentStatus") == "paid"
    seat = read(client, os.environ["SEATS_TABLE"], seat_key(order))
    # An unknown post-payment outcome is never compensated by freeing inventory.
    review = paid or stage == "FULFILLMENT" or (owned(seat, order) and seat.get("status") == "sold")
    error_name = str(order.get("error", {}).get("Error", "Unknown"))[:128]
    status = "REVIEW_REQUIRED" if review else (
        "REJECTED" if stage == "RESERVATION" and error_name == "SeatUnavailable" else "FAILED"
    )
    order_condition, values = identity(order)
    if review:
        # A concurrent ticket transaction must either win completely or be
        # blocked by REVIEW_REQUIRED; never downgrade an already-issued ticket.
        guard = " AND attribute_not_exists(ticketStatus)"
        if paid:
            guard += " AND paymentStatus = :paid"
            values[":paid"] = "paid"
    else:
        guard = " AND orderStatus IN (:pending, :reserved) AND attribute_not_exists(paymentStatus)"
        values.update({":pending": "PENDING", ":reserved": "RESERVED"})
    values.update({":status": status, ":stage": stage, ":error": error_name, ":now": int(time.time())})
    operations = [{"Update": {
        "TableName": os.environ["ORDERS_TABLE"], "Key": encode({"orderId": order["orderId"]}),
        "UpdateExpression": "SET orderStatus = :status, failureStage = :stage, failureError = :error, failedAt = :now REMOVE holdExpiresAt",
        "ConditionExpression": order_condition + guard,
        "ExpressionAttributeValues": encode(values),
    }}]
    release = not review and owned(seat, order) and seat.get("status") == "held"
    if release:
        operations.append({"Update": {
            "TableName": os.environ["SEATS_TABLE"], "Key": encode(seat_key(order)),
            "UpdateExpression": "SET #s = :free REMOVE holdExpiresAt, heldBy, heldForUser",
            "ConditionExpression": "#s = :held AND heldBy = :order AND heldForUser = :user",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": encode({":free": "free", ":held": "held", ":order": order["orderId"], ":user": order["userId"]}),
        }})
    try:
        client.transact_write_items(TransactItems=operations)
    except ClientError as exc:
        if condition_failed(exc):
            # Re-read on the bounded workflow retry. Payment, another owner, or
            # ticket confirmation may have raced this compensation transaction.
            raise ConcurrentOrderChange("Failure state changed; reconcile again") from exc
        raise
    return {"orderId": order["orderId"], "orderStatus": status, "released": bool(release)}
