import os

import boto3

_ses = boto3.client("ses")


def handler(event, context):
    order = event
    addr = os.environ["NOTIFY_EMAIL"]

    subject = f"Your ticket for event {order['eventId']}"
    body = (
        f"Your purchase is confirmed.\n\n"
        f"Order: {order['orderId']}\n"
        f"Event: {order['eventId']}\n"
        f"Seat:  {order['seatId']}\n"
        f"Ticket code: {order.get('qrPayload', '')}\n"
        f"QR image: {order.get('qrUrl', '')}\n"
    )

    # SES sandbox: send FROM and TO the same verified address.
    _ses.send_email(
        Source=addr,
        Destination={"ToAddresses": [addr]},
        Message={"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}},
    )

    return {**order, "emailStatus": "sent"}
