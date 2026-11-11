import time
import uuid


class PaymentFailed(Exception):
    pass


def handler(event, context):
    # Simulated payment. Deterministic so the compensation path is demoable:
    # it fails only when the order input carries {"forceFail": true}.
    order = event
    if order.get("forceFail") is True:
        raise PaymentFailed(f"Payment declined for order {order['orderId']}")

    payment = {
        "paymentId": "pay-" + uuid.uuid4().hex[:12],
        "paymentStatus": "paid",
        "paidAt": int(time.time()),
    }
    return {**order, **payment}
