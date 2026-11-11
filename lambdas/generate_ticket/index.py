import os
import time
import urllib.parse

import boto3

_ddb = boto3.resource("dynamodb")


class SeatLost(Exception):
    pass


def handler(event, context):
    order = event
    order_id = order["orderId"]
    event_id = order["eventId"]
    seat_id = order["seatId"]

    issued_at = int(time.time())
    qr_payload = f"TICKET|{order_id}|{event_id}|{seat_id}|{issued_at}"
    # Build the QR image URL only; do not fetch it.
    qr_url = "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=" + urllib.parse.quote(qr_payload)

    # Payment succeeded, so promote the seat from "held" to the final "sold"
    # state. Conditional on it still being held by THIS order: a sold seat can
    # never be reserved again, which is what stops overselling when the hold
    # would otherwise expire. If the hold was lost (expired + taken by someone
    # else) we fail loudly rather than issue a ticket for a seat we don't own.
    seats = _ddb.Table(os.environ["SEATS_TABLE"])
    try:
        seats.update_item(
            Key={"eventId": event_id, "seatId": seat_id},
            UpdateExpression="SET #s = :sold REMOVE holdExpiresAt",
            ConditionExpression="#s = :held AND heldBy = :order",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":sold": "sold", ":held": "held", ":order": order_id},
        )
    except _ddb.meta.client.exceptions.ConditionalCheckFailedException:
        raise SeatLost(f"Seat {seat_id} for event {event_id} is no longer held by order {order_id}")

    # Augment the order created by Part C (update_item, not put_item).
    orders = _ddb.Table(os.environ["ORDERS_TABLE"])
    orders.update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET ticketStatus = :t, qrPayload = :p, qrUrl = :u, issuedAt = :i",
        ExpressionAttributeValues={
            ":t": "issued",
            ":p": qr_payload,
            ":u": qr_url,
            ":i": issued_at,
        },
    )

    return {
        **order,
        "ticketStatus": "issued",
        "seatStatus": "sold",
        "qrPayload": qr_payload,
        "qrUrl": qr_url,
        "issuedAt": issued_at,
    }
