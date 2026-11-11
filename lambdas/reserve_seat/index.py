import os
import time

import boto3

_ddb = boto3.resource("dynamodb")
HOLD_SECONDS = int(os.environ.get("HOLD_SECONDS", "900"))


class SeatUnavailable(Exception):
    pass


def handler(event, context):
    # Invoked by Step Functions with the raw order object (not an API event).
    order = event
    event_id = order["eventId"]
    seat_id = order["seatId"]
    order_id = order["orderId"]
    user_id = order["userId"]

    now = int(time.time())
    expires = now + HOLD_SECONDS

    table = _ddb.Table(os.environ["SEATS_TABLE"])
    try:
        # Idempotent conditional hold: succeeds when the seat is absent,
        # free, or its previous hold has already expired.
        table.update_item(
            Key={"eventId": event_id, "seatId": seat_id},
            UpdateExpression="SET #s = :held, holdExpiresAt = :exp, heldBy = :order, heldForUser = :user",
            ConditionExpression="attribute_not_exists(seatId) OR #s = :free OR holdExpiresAt < :now",
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
