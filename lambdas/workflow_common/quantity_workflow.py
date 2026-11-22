"""General admission v2: order-guarded, atomic inventory and ticket transitions.

No TTL deletes reservations. Every decrement is paired with an order transition;
unknown paid outcomes retain inventory for reconciliation.
"""
import hashlib
import os
import time
from decimal import Decimal
from urllib.parse import quote

import boto3
from botocore.exceptions import ClientError
from purchase_common import ConcurrentOrderChange, OrderMismatch, condition_failed, encode, read

MAX_QUANTITY = 20


class InventoryUnavailable(Exception):
    pass


class QuantityPaymentFailed(Exception):
    pass


def load(order):
    for key in ("orderId", "userId", "eventId"):
        value = order.get(key)
        if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 128:
            raise OrderMismatch("Invalid order identity")
    q = order.get("quantity")
    if order.get("schemaVersion") != 2 or isinstance(q, bool) or not isinstance(q, (int, Decimal)) or q != int(q) or not 1 <= q <= MAX_QUANTITY:
        raise OrderMismatch("Invalid ticket quantity")
    client = boto3.client("dynamodb")
    saved = read(client, os.environ["ORDERS_TABLE"], {"orderId": order["orderId"]})
    if not saved or any(saved.get(k) != order[k] for k in ("schemaVersion", "userId", "eventId", "quantity")):
        raise OrderMismatch("A matching persisted quantity order is required")
    return client, saved


def identity(order):
    return ("attribute_exists(orderId) AND schemaVersion = :v AND userId = :user AND eventId = :event AND quantity = :q",
            {":v": 2, ":user": order["userId"], ":event": order["eventId"], ":q": order["quantity"]})


def order_update(order, expression, guard, values):
    condition, base = identity(order)
    return {"Update": {"TableName": os.environ["ORDERS_TABLE"], "Key": encode({"orderId": order["orderId"]}),
                       "UpdateExpression": expression, "ConditionExpression": condition + " AND " + guard,
                       "ExpressionAttributeValues": encode({**base, **values})}}


def reserve(order):
    client, saved = load(order)
    if saved.get("orderStatus") in ("RESERVED", "PAID", "CONFIRMED") and saved.get("inventoryStatus") in ("HELD", "SOLD"):
        return {**order, "inventoryStatus": saved["inventoryStatus"]}
    if saved.get("orderStatus") != "PENDING":
        raise InventoryUnavailable("Order is no longer reservable")
    event = read(client, os.environ["EVENTS_TABLE"], {"eventId": order["eventId"]})
    q = int(order["quantity"])
    if not event or event.get("inventoryVersion") != 2 or event.get("source") == "ticketmaster" or event.get("available", 0) < q:
        raise InventoryUnavailable("Insufficient tickets or inventory is not ready")
    price = event.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, Decimal)) or not Decimal(price).is_finite() or price < 0:
        raise InventoryUnavailable("Invalid event price")
    expires = int(time.time()) + int(os.environ.get("HOLD_SECONDS", "900"))
    if expires <= time.time():
        raise ValueError("HOLD_SECONDS must be positive")
    try:
        client.transact_write_items(TransactItems=[
            {"Update": {
                "TableName": os.environ["EVENTS_TABLE"], "Key": encode({"eventId": order["eventId"]}),
                "UpdateExpression": "SET available = available - :q, reserved = reserved + :q",
                "ConditionExpression": "inventoryVersion = :v AND available >= :q AND #cap = :cap AND price = :price AND (attribute_not_exists(#src) OR #src <> :external)",
                "ExpressionAttributeNames": {"#cap": "capacity", "#src": "source"},
                "ExpressionAttributeValues": encode({":v": 2, ":q": q, ":cap": event["capacity"], ":price": price, ":external": "ticketmaster"}),
            }},
            order_update(order, "SET orderStatus = :held, inventoryStatus = :inventory, holdExpiresAt = :expires, unitPrice = :price, totalPrice = :total",
                         "orderStatus = :pending AND attribute_not_exists(inventoryStatus)",
                         {":held": "RESERVED", ":inventory": "HELD", ":expires": expires, ":price": price, ":total": price * q, ":pending": "PENDING"}),
        ])
    except ClientError as exc:
        if not condition_failed(exc):
            raise
        _, latest = load(order)
        if latest.get("orderStatus") in ("RESERVED", "PAID", "CONFIRMED") and latest.get("inventoryStatus") in ("HELD", "SOLD"):
            return {**order, "inventoryStatus": latest["inventoryStatus"]}
        current = read(client, os.environ["EVENTS_TABLE"], {"eventId": order["eventId"]})
        if current and current.get("available", 0) < q:
            raise InventoryUnavailable("Insufficient tickets remaining") from exc
        raise ConcurrentOrderChange("Inventory or order changed; retry reservation") from exc
    return {**order, "inventoryStatus": "HELD"}


def pay(order):
    client, saved = load(order)
    if saved.get("paymentStatus") == "paid":
        return {**order, "paymentStatus": "paid"}
    if order.get("forceFail") is True:
        raise QuantityPaymentFailed("Simulated payment declined")
    now = int(time.time())
    operation = order_update(order,
        "SET orderStatus = :state, paymentStatus = :paid, paidAt = :now, paymentId = :id",
        "orderStatus = :reserved AND inventoryStatus = :held AND holdExpiresAt >= :now AND attribute_not_exists(paymentStatus)",
        {":state": "PAID", ":paid": "paid", ":now": now, ":id": "pay-" + hashlib.sha256(order["orderId"].encode()).hexdigest(), ":reserved": "RESERVED", ":held": "HELD"})["Update"]
    try:
        client.update_item(**operation)
    except ClientError as exc:
        if not condition_failed(exc):
            raise
        _, latest = load(order)
        if latest.get("paymentStatus") != "paid":
            raise QuantityPaymentFailed("Reservation is no longer payable") from exc
    return {**order, "paymentStatus": "paid"}


def build_tickets(order, saved):
    tickets = []
    for index in range(int(order["quantity"])):
        ticket_id = "ticket-" + hashlib.sha256(f"{order['orderId']}:{index}".encode()).hexdigest()
        payload = f"TICKET|{ticket_id}|{order['eventId']}|{int(saved['paidAt'])}"
        tickets.append({"orderId": order["orderId"], "ticketId": ticket_id, "eventId": order["eventId"],
                        "ticketNumber": index + 1, "issuedAt": saved["paidAt"], "qrPayload": payload,
                        "qrUrl": "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=" + quote(payload)})
    return tickets


def issue(order):
    client, saved = load(order)
    if saved.get("orderStatus") == "CONFIRMED" and saved.get("ticketStatus") == "issued":
        return {**order, "ticketStatus": "issued"}
    # A paid hold remains reserved even after its timeout until reconciled.
    if saved.get("orderStatus") not in ("PAID", "REVIEW_REQUIRED") or saved.get("paymentStatus") != "paid" or saved.get("inventoryStatus") != "HELD":
        raise OrderMismatch("A durably paid reservation is required")
    tickets = build_tickets(order, saved)
    operations = [
        {"Put": {"TableName": os.environ["TICKETS_TABLE"], "Item": encode(ticket), "ConditionExpression": "attribute_not_exists(ticketId)"}}
        for ticket in tickets
    ]
    operations += [
        {"Update": {"TableName": os.environ["EVENTS_TABLE"], "Key": encode({"eventId": order["eventId"]}),
                    "UpdateExpression": "SET reserved = reserved - :q, sold = sold + :q",
                    "ConditionExpression": "inventoryVersion = :v AND reserved >= :q",
                    "ExpressionAttributeValues": encode({":v": 2, ":q": order["quantity"]})}},
        order_update(order, "SET orderStatus = :confirmed, ticketStatus = :issued, inventoryStatus = :sold REMOVE holdExpiresAt, failureStage, failureError, failedAt",
                     "orderStatus IN (:paidState, :review) AND paymentStatus = :paid AND inventoryStatus = :held AND attribute_not_exists(ticketStatus)",
                     {":confirmed": "CONFIRMED", ":issued": "issued", ":sold": "SOLD", ":paidState": "PAID", ":review": "REVIEW_REQUIRED", ":paid": "paid", ":held": "HELD"}),
    ]
    try:
        client.transact_write_items(TransactItems=operations)
    except ClientError as exc:
        if not condition_failed(exc):
            raise
        _, latest = load(order)
        if latest.get("orderStatus") != "CONFIRMED" or latest.get("ticketStatus") != "issued":
            raise ConcurrentOrderChange("Ticket issuance needs reconciliation") from exc
    return {**order, "ticketStatus": "issued"}


def notify(order):
    client, saved = load(order)
    if saved.get("orderStatus") != "CONFIRMED" or saved.get("ticketStatus") != "issued":
        raise OrderMismatch("Only confirmed tickets can be notified")
    operation = order_update(order, "SET emailStatus = :email", "orderStatus = :confirmed AND ticketStatus = :issued",
                             {":email": "not_sent", ":confirmed": "CONFIRMED", ":issued": "issued"})["Update"]
    client.update_item(**operation)
    return {"orderId": order["orderId"], "emailStatus": "not_sent"}


def compensate(envelope):
    order = envelope.get("order", envelope)
    stage = envelope.get("failureStage", "PAYMENT")
    client, saved = load(order)
    if stage == "NOTIFICATION":
        return notify(order)
    if saved.get("orderStatus") in ("CONFIRMED", "FAILED", "REJECTED", "REVIEW_REQUIRED"):
        return {"orderId": order["orderId"], "orderStatus": saved["orderStatus"]}
    paid = saved.get("paymentStatus") == "paid"
    status = "REVIEW_REQUIRED" if paid or stage == "FULFILLMENT" else ("REJECTED" if stage == "RESERVATION" else "FAILED")
    error = str(order.get("error", {}).get("Error", "Unknown"))[:128]
    values = {":status": status, ":stage": stage, ":error": error, ":previous": saved["orderStatus"]}
    guard = "orderStatus = :previous AND attribute_not_exists(ticketStatus)"
    if paid:
        guard += " AND paymentStatus = :paid"
        values[":paid"] = "paid"
    else:
        guard += " AND attribute_not_exists(paymentStatus)"
    release = not paid and stage != "FULFILLMENT" and saved.get("inventoryStatus") == "HELD"
    expression = "SET orderStatus = :status, failureStage = :stage, failureError = :error"
    if release:
        expression += ", inventoryStatus = :released"
        values[":released"] = "RELEASED"
        guard += " AND inventoryStatus = :held"
        values[":held"] = "HELD"
    expression += " REMOVE holdExpiresAt"
    operations = [order_update(order, expression, guard, values)]
    if release:
        operations.append({"Update": {"TableName": os.environ["EVENTS_TABLE"], "Key": encode({"eventId": order["eventId"]}),
            "UpdateExpression": "SET reserved = reserved - :q, available = available + :q",
            "ConditionExpression": "inventoryVersion = :v AND reserved >= :q",
            "ExpressionAttributeValues": encode({":v": 2, ":q": order["quantity"]})}})
    try:
        client.transact_write_items(TransactItems=operations)
    except ClientError as exc:
        if condition_failed(exc):
            raise ConcurrentOrderChange("Payment or ticket issuance raced compensation") from exc
        raise
    return {"orderId": order["orderId"], "orderStatus": status, "released": release}
