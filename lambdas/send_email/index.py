"""Best-effort SES notification after durable ticket confirmation."""

import logging
import os

import boto3
from purchase_common import OrderMismatch, load_order, save_email_status

logger = logging.getLogger(__name__)


def handler(event, context):
    client, saved = load_order(event)
    if saved.get("orderStatus") != "CONFIRMED" or saved.get("ticketStatus") != "issued":
        raise OrderMismatch("Only a confirmed purchase can be emailed")
    if saved.get("emailStatus") == "sent":
        return {"orderId": event["orderId"], "emailStatus": "sent"}
    addr = os.environ["NOTIFY_EMAIL"]
    body = (
        f"Your purchase is confirmed.\n\nOrder: {event['orderId']}\n"
        f"Event: {event['eventId']}\nSeat: {event['seatId']}\n"
        f"Ticket code: {saved['qrPayload']}\nQR image: {saved['qrUrl']}\n"
    )
    try:
        boto3.client("ses").send_email(
            Source=addr, Destination={"ToAddresses": [addr]},
            Message={"Subject": {"Data": f"Your ticket for event {event['eventId']}"},
                     "Body": {"Text": {"Data": body}}},
        )
        status = "sent"
    except Exception as exc:
        logger.warning("Ticket notification failed for %s (%s)", event["orderId"], type(exc).__name__)
        status = "not_sent"
    status = save_email_status(client, event, status)
    return {"orderId": event["orderId"], "emailStatus": status}
