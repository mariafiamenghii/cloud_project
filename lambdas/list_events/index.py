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
    # Fine for the MVP. Later: pagination and filters by city/date/genre.
    items = table.scan().get("Items", [])
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(items, default=_default),
    }
