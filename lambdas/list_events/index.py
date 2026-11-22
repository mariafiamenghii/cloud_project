import json
import os
from decimal import Decimal

import boto3

table = boto3.resource("dynamodb").Table(os.environ["EVENTS_TABLE"])


def _default(o):
    # DynamoDB returns numbers as Decimal, which json cannot print.
    if isinstance(o, Decimal):
        return int(o) if o % 1 == 0 else float(o)
    raise TypeError


def handler(event, context):
    event_id = (event.get("pathParameters") or {}).get("eventId")
    if event_id:
        item = table.get_item(Key={"eventId": event_id}, ConsistentRead=True).get("Item")
        if not item or item.get("source") == "ticketmaster":
            return {"statusCode": 404, "body": json.dumps({"error": "Internal event not found"})}
        fields = ("eventId", "capacity", "sold", "reserved", "available", "inventoryVersion", "price")
        body = {key: item[key] for key in fields if key in item}
        body["maxPurchaseQuantity"] = 20
        return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body, default=_default)}
    # Fine for the MVP. Later: pagination and filters by city/date/genre.
    page = table.scan(ConsistentRead=True)
    items = page.get("Items", [])
    while page.get("LastEvaluatedKey"):
        page = table.scan(ConsistentRead=True, ExclusiveStartKey=page["LastEvaluatedKey"])
        items.extend(page.get("Items", []))
    for item in items:
        if item.get("inventoryVersion") == 2 and item.get("source") != "ticketmaster":
            item["maxPurchaseQuantity"] = 20
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(items, default=_default),
    }
