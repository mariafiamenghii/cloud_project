"""Load sample events into the DynamoDB events table.

Run from the repo root:   python scripts/load_events.py
It is safe to run twice: the eventId is built from artist + date + venue,
so the same concert is overwritten instead of duplicated.
"""
import json
import os
import time
import uuid
from decimal import Decimal

import boto3

PREFIX = os.environ.get("PREFIX", "ticketing")      # same as var.prefix in Terraform
REGION = os.environ.get("AWS_REGION", "us-east-1")

table = boto3.resource("dynamodb", region_name=REGION).Table(f"{PREFIX}-events")

path = os.path.join(os.path.dirname(__file__), "..", "data", "sample_events.json")
with open(path, encoding="utf-8") as f:
    events = json.load(f, parse_float=Decimal)

for e in events:
    key = f"{e['artist']}|{e['date']}|{e['venue']}"
    e["eventId"] = str(uuid.uuid5(uuid.NAMESPACE_URL, key))
    e["artistId"] = "sample-import"
    e["createdAt"] = int(time.time())
    table.put_item(Item=e)

print(f"{len(events)} events loaded into {PREFIX}-events")
