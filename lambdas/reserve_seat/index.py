"""Atomically validate event capacity and reserve a canonical seat."""

import os
import time
from decimal import Decimal

from botocore.exceptions import ClientError
from purchase_common import condition_failed, encode, identity, load_order, owned, read, seat_key


class SeatUnavailable(Exception):
    pass


def handler(event, context):
    client, saved = load_order(event)
    now = int(time.time())
    if saved.get("paymentStatus") == "paid":
        seat = read(client, os.environ["SEATS_TABLE"], seat_key(event))
        if owned(seat, event) and (seat.get("status") == "sold" or
                                  (seat.get("status") == "held" and seat.get("holdExpiresAt", 0) >= now)):
            return {**event, "seatStatus": seat["status"]}
        raise SeatUnavailable("Paid order needs reconciliation; its seat is no longer owned")
    if saved.get("orderStatus") not in ("PENDING", "RESERVED"):
        raise SeatUnavailable("Order is no longer reservable")

    item = read(client, os.environ["EVENTS_TABLE"], {"eventId": event["eventId"]})
    capacity = item.get("capacity") if item else None
    if (isinstance(capacity, bool) or not isinstance(capacity, (int, Decimal)) or
            (isinstance(capacity, Decimal) and not capacity.is_finite()) or
            capacity != int(capacity) or int(event["seatId"]) > capacity or capacity <= 0 or
            item.get("source") == "ticketmaster"):
        raise SeatUnavailable("Event or seat is not sellable")
    expires = now + int(os.environ.get("HOLD_SECONDS", "900"))
    if expires <= now:
        raise ValueError("HOLD_SECONDS must be positive")
    order_condition, values = identity(event)
    try:
        client.transact_write_items(TransactItems=[
            {"ConditionCheck": {
                "TableName": os.environ["EVENTS_TABLE"], "Key": encode({"eventId": event["eventId"]}),
                "ConditionExpression": "#capacity = :capacity AND (attribute_not_exists(#source) OR #source <> :external)",
                "ExpressionAttributeNames": {"#capacity": "capacity", "#source": "source"},
                "ExpressionAttributeValues": encode({":capacity": capacity, ":external": "ticketmaster"}),
            }},
            {"Update": {
                "TableName": os.environ["SEATS_TABLE"], "Key": encode(seat_key(event)),
                "UpdateExpression": "SET #s = :held, holdExpiresAt = :expires, heldBy = :order, heldForUser = :user",
                "ConditionExpression": ("attribute_not_exists(seatId) OR #s = :free OR "
                                        "(#s = :held AND holdExpiresAt < :now) OR "
                                        "(#s = :held AND heldBy = :order AND heldForUser = :user)"),
                "ExpressionAttributeNames": {"#s": "status"},
                "ExpressionAttributeValues": encode({":held": "held", ":free": "free", ":now": now,
                                                     ":expires": expires, ":order": event["orderId"], ":user": event["userId"]}),
            }},
            {"Update": {
                "TableName": os.environ["ORDERS_TABLE"], "Key": encode({"orderId": event["orderId"]}),
                "UpdateExpression": "SET orderStatus = :reserved, holdExpiresAt = :expires",
                "ConditionExpression": order_condition + " AND orderStatus IN (:pending, :reserved) AND attribute_not_exists(paymentStatus)",
                "ExpressionAttributeValues": encode({**values, ":reserved": "RESERVED", ":pending": "PENDING", ":expires": expires}),
            }},
        ])
    except ClientError as exc:
        if condition_failed(exc):
            raise SeatUnavailable("Seat, capacity or order state changed") from exc
        raise
    return {**event, "seatStatus": "held", "holdExpiresAt": expires}
