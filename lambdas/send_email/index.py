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

    # Best-effort email: if SES is blocked (Academy/Innovation Sandbox) or the
    # address is not a verified identity, don't fail the purchase. The seat and
    # ticket are already done, so we just record why the email didn't go out.
    try:
        # SES sandbox: send FROM and TO the same verified address.
        _ses.send_email(
            Source=addr,
            Destination={"ToAddresses": [addr]},
            Message={"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}},
        )
        status = "sent"
    except Exception as e:  # SES blocked or address not verified
        print("Email not sent:", e)
        status = "not_sent"

    return {**order, "emailStatus": status}
