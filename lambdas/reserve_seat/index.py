import os
import time

import boto3

_ddb = boto3.resource("dynamodb")
HOLD_SECONDS = int(os.environ.get("HOLD_SECONDS", "900"))


class SeatUnavailable(Exception):
    pass


def _check_capacity(event_id, seat_id):
    # Agreed demo convention: seatIds are "1".."capacity" for the event.
    # Reject anything that is not an integer in that range so we never hold a
    # seat that does not exist for the event.
    events_table_name = os.environ.get("EVENTS_TABLE")
    if not events_table_name:
        return  # capacity check disabled if the table is not wired in

    try:
        seat_num = int(seat_id)
    except (TypeError, ValueError):
        raise SeatUnavailable(f"Seat {seat_id} is not a valid seat number")

    events = _ddb.Table(events_table_name)
    item = events.get_item(Key={"eventId": event_id}).get("Item")
    if not item:
        raise SeatUnavailable(f"Event {event_id} does not exist")

    capacity = int(item.get("capacity", 0))
    if capacity <= 0:
        # capacity 0 = imported/not-sellable event (e.g. Ticketmaster imports)
        raise SeatUnavailable(f"Event {event_id} has no sellable seats")
    if seat_num < 1 or seat_num > capacity:
        raise SeatUnavailable(
            f"Seat {seat_id} is outside the event capacity (1..{capacity})"
        )


def handler(event, context):
    # Invoked by Step Functions with the raw order object (not an API event).
    order = event
    event_id = order["eventId"]
    seat_id = order["seatId"]
    order_id = order["orderId"]
    user_id = order["userId"]

    _check_capacity(event_id, seat_id)

    now = int(time.time())
    expires = now + HOLD_SECONDS

    table = _ddb.Table(os.environ["SEATS_TABLE"])
    try:
        # Conditional hold. Succeeds only when the seat is:
        #   - absent (never touched), or
        #   - free, or
        #   - an expired hold, or
        #   - already held by THIS order (idempotent retry).
        # A seat that is "sold" can NEVER be re-held -> no overselling.
        table.update_item(
            Key={"eventId": event_id, "seatId": seat_id},
            UpdateExpression=(
                "SET #s = :held, holdExpiresAt = :exp, heldBy = :order, heldForUser = :user"
            ),
            ConditionExpression=(
                "attribute_not_exists(seatId) "
                "OR #s = :free "
                "OR (#s = :held AND holdExpiresAt < :now) "
                "OR (#s = :held AND heldBy = :order)"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":held": "held",
                ":free": "free",
                ":now": now,
                ":exp": expires,
                ":order": order_id,
                ":user": user_id,
            },
        )
    except _ddb.meta.client.exceptions.ConditionalCheckFailedException:
        raise SeatUnavailable(f"Seat {seat_id} for event {event_id} is not available")

    return {**order, "seatStatus": "held", "holdExpiresAt": expires}
