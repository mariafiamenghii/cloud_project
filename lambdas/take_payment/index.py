"""Persist a retry-safe simulated payment while the order owns a valid hold."""

import hashlib
import os
import time

from botocore.exceptions import ClientError
from purchase_common import condition_failed, encode, identity, load_order, seat_key


class PaymentFailed(Exception):
    pass


def _result(event, saved):
    return {**event, "paymentId": saved["paymentId"], "paymentStatus": "paid", "paidAt": int(saved["paidAt"])}


def handler(event, context):
    client, saved = load_order(event)
    if saved.get("paymentStatus") == "paid":
        return _result(event, saved)
    if event.get("forceFail") is True:
        raise PaymentFailed("Simulated payment declined")
    now = int(time.time())
    payment = {"paymentId": "pay-" + hashlib.sha256(event["orderId"].encode()).hexdigest()[:24],
               "paymentStatus": "paid", "paidAt": now}
    order_condition, values = identity(event)
    try:
        client.transact_write_items(TransactItems=[
            {"ConditionCheck": {
                "TableName": os.environ["SEATS_TABLE"], "Key": encode(seat_key(event)),
                "ConditionExpression": "#s = :held AND heldBy = :order AND heldForUser = :user AND holdExpiresAt >= :now",
                "ExpressionAttributeNames": {"#s": "status"},
                "ExpressionAttributeValues": encode({":held": "held", ":order": event["orderId"], ":user": event["userId"], ":now": now}),
            }},
            {"Update": {
                "TableName": os.environ["ORDERS_TABLE"], "Key": encode({"orderId": event["orderId"]}),
                "UpdateExpression": "SET orderStatus = :paidState, paymentStatus = :paid, paymentId = :id, paidAt = :now",
                "ConditionExpression": order_condition + " AND orderStatus = :reserved AND attribute_not_exists(paymentStatus)",
                "ExpressionAttributeValues": encode({**values, ":reserved": "RESERVED", ":paidState": "PAID",
                                                     ":paid": "paid", ":id": payment["paymentId"], ":now": now}),
            }},
        ])
    except ClientError as exc:
        if not condition_failed(exc):
            raise
        _, saved = load_order(event)
        if saved.get("paymentStatus") == "paid":
            return _result(event, saved)
        raise PaymentFailed("Order does not own a valid payable hold") from exc
    return _result(event, payment)
