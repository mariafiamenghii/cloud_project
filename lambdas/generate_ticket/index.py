"""Confirm the owned seat and issue its stable ticket in one transaction."""

import os
import time
import urllib.parse

from botocore.exceptions import ClientError
from purchase_common import condition_failed, encode, identity, load_order, owned, read, seat_key, ticket_result


class SeatLost(Exception):
    pass


def _existing(event, client, saved):
    seat = read(client, os.environ["SEATS_TABLE"], seat_key(event))
    if not owned(seat, event) or seat.get("status") != "sold":
        raise SeatLost("Issued ticket and sold seat require reconciliation")
    return ticket_result(event, saved)


def handler(event, context):
    client, saved = load_order(event)
    if saved.get("ticketStatus") == "issued":
        return _existing(event, client, saved)
    if saved.get("paymentStatus") != "paid" or saved.get("orderStatus") != "PAID":
        raise SeatLost("A durably paid order is required")
    now = int(time.time())
    # Payment's persisted timestamp keeps QR content stable under every retry.
    issued_at = int(saved["paidAt"])
    payload = f"TICKET|{event['orderId']}|{event['eventId']}|{event['seatId']}|{issued_at}"
    url = "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=" + urllib.parse.quote(payload)
    ticket = {"qrPayload": payload, "qrUrl": url, "issuedAt": issued_at}
    order_condition, values = identity(event)
    try:
        client.transact_write_items(TransactItems=[
            {"Update": {
                "TableName": os.environ["SEATS_TABLE"], "Key": encode(seat_key(event)),
                "UpdateExpression": "SET #s = :sold REMOVE holdExpiresAt",
                "ConditionExpression": "#s = :held AND heldBy = :order AND heldForUser = :user AND holdExpiresAt >= :now",
                "ExpressionAttributeNames": {"#s": "status"},
                "ExpressionAttributeValues": encode({":sold": "sold", ":held": "held", ":order": event["orderId"],
                                                     ":user": event["userId"], ":now": now}),
            }},
            {"Update": {
                "TableName": os.environ["ORDERS_TABLE"], "Key": encode({"orderId": event["orderId"]}),
                "UpdateExpression": "SET orderStatus = :confirmed, ticketStatus = :issued, qrPayload = :payload, qrUrl = :url, issuedAt = :issuedAt REMOVE holdExpiresAt",
                "ConditionExpression": order_condition + " AND paymentStatus = :paid AND orderStatus = :paidState AND attribute_not_exists(ticketStatus)",
                "ExpressionAttributeValues": encode({**values, ":paid": "paid", ":paidState": "PAID", ":confirmed": "CONFIRMED",
                                                     ":issued": "issued", ":payload": payload, ":url": url, ":issuedAt": issued_at}),
            }},
        ])
    except ClientError as exc:
        if not condition_failed(exc):
            raise
        _, saved = load_order(event)
        if saved.get("ticketStatus") == "issued":
            return _existing(event, client, saved)
        raise SeatLost("Hold expired, ownership was lost, or order state changed") from exc
    return ticket_result(event, ticket)
