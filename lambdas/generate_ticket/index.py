import os
import time
import urllib.parse

import boto3

_ddb = boto3.resource("dynamodb")


def handler(event, context):
    order = event
    order_id = order["orderId"]
    event_id = order["eventId"]
    seat_id = order["seatId"]

    issued_at = int(time.time())
    qr_payload = f"TICKET|{order_id}|{event_id}|{seat_id}|{issued_at}"
    # Build the QR image URL only; do not fetch it.
    qr_url = "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=" + urllib.parse.quote(qr_payload)

    # Augment the order created by Part C (update_item, not put_item).
    table = _ddb.Table(os.environ["ORDERS_TABLE"])
    table.update_item(
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
        "qrPayload": qr_payload,
        "qrUrl": qr_url,
        "issuedAt": issued_at,
    }
