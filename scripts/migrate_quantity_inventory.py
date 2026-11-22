"""Dry-run by default. Requires frozen intake/event creation and drained legacy work.

Run with Python 3.12 + boto3. Never changes orders, seats, or historical QR codes.
The --apply flag is for an explicitly approved migration only.
"""
import argparse
import hashlib
import json
from decimal import Decimal

import boto3


def scan(table):
    page = table.scan(ConsistentRead=True)
    items = page.get("Items", [])
    while page.get("LastEvaluatedKey"):
        page = table.scan(ConsistentRead=True, ExclusiveStartKey=page["LastEvaluatedKey"])
        items.extend(page.get("Items", []))
    return items


def migration_plan(events, orders, seats):
    plans = []
    by_id = {order["orderId"]: order for order in orders}
    for event in events:
        if event.get("source") == "ticketmaster" or event.get("inventoryVersion") == 2:
            continue
        event_id = event["eventId"]
        capacity = event.get("capacity")
        if isinstance(capacity, bool) or not isinstance(capacity, (int, Decimal)) or not Decimal(capacity).is_finite() or capacity != int(capacity) or capacity < 0:
            raise ValueError(f"Invalid capacity: {event_id}")
        related = [o for o in orders if o.get("eventId") == event_id]
        if any(o.get("orderStatus") not in ("CONFIRMED", "FAILED", "REJECTED") for o in related):
            raise ValueError(f"Unresolved order requires reconciliation: {event_id}")
        sold = [o for o in related if o.get("orderStatus") == "CONFIRMED"]
        if any(o.get("ticketStatus") != "issued" or o.get("paymentStatus") != "paid" or not o.get("qrPayload") or "quantity" in o for o in sold):
            raise ValueError(f"Unexpected historical ticket schema: {event_id}")
        event_seats = [s for s in seats if s.get("eventId") == event_id]
        if any(s.get("status") == "held" for s in event_seats):
            raise ValueError(f"Outstanding legacy hold: {event_id}")
        sold_seats = [s for s in event_seats if s.get("status") == "sold"]
        if len(sold_seats) != len(sold) or any(
            s.get("heldBy") not in by_id or by_id[s["heldBy"]] not in sold or
            by_id[s["heldBy"]].get("seatId") != s.get("seatId") for s in sold_seats
        ) or len({s.get("heldBy") for s in sold_seats}) != len(sold):
            raise ValueError(f"Historical sold seats/orders disagree: {event_id}")
        if len(sold) > capacity:
            raise ValueError(f"Historical sales exceed capacity: {event_id}")
        digest = hashlib.sha256(json.dumps(sorted(o["orderId"] for o in sold)).encode()).hexdigest()
        plans.append({"eventId": event_id, "capacity": int(capacity), "sold": len(sold), "reserved": 0,
                      "available": int(capacity) - len(sold), "migrationDigest": digest})
    return plans


def assert_quiet(session, prefix, require_frozen):
    client = session.client("lambda")
    if require_frozen:
        for suffix in ("create-purchase", "create-event"):
            if client.get_function_concurrency(FunctionName=f"{prefix}-{suffix}").get("ReservedConcurrentExecutions") != 0:
                raise RuntimeError("Freeze purchase intake and event creation before applying migration")
    sqs = session.client("sqs")
    for suffix in ("purchase-queue", "purchase-dlq"):
        url = sqs.get_queue_url(QueueName=f"{prefix}-{suffix}")["QueueUrl"]
        counts = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible", "ApproximateNumberOfMessagesDelayed"])["Attributes"]
        if any(int(value) for value in counts.values()):
            raise RuntimeError("Queue/DLQ must be empty; do not consume or reinterpret old messages")
    account = session.client("sts").get_caller_identity()["Account"]
    arn = f"arn:aws:states:{session.region_name}:{account}:stateMachine:{prefix}-purchase-workflow"
    if session.client("stepfunctions").list_executions(stateMachineArn=arn, statusFilter="RUNNING", maxResults=1)["executions"]:
        raise RuntimeError("Wait for running workflows before migrating")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--prefix", default="ticketing")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()
    session = boto3.Session(region_name=args.region)
    assert_quiet(session, args.prefix, args.apply)
    ddb = session.resource("dynamodb")
    events = ddb.Table(f"{args.prefix}-events")
    plans = migration_plan(scan(events), scan(ddb.Table(f"{args.prefix}-orders")), scan(ddb.Table(f"{args.prefix}-seats")))
    print(json.dumps({"apply": args.apply, "events": plans}, indent=2))
    if args.apply:
        assert_quiet(session, args.prefix, True)
        for item in plans:
            events.update_item(Key={"eventId": item["eventId"]},
                UpdateExpression="SET inventoryVersion = :v, #sold = :sold, #reserved = :zero, available = :available, legacySold = :sold, migrationDigest = :digest",
                ConditionExpression="attribute_not_exists(inventoryVersion) AND #capacity = :capacity AND (attribute_not_exists(#source) OR #source <> :external)",
                ExpressionAttributeNames={"#sold": "sold", "#reserved": "reserved", "#capacity": "capacity", "#source": "source"},
                ExpressionAttributeValues={":v": 2, ":sold": item["sold"], ":zero": 0, ":available": item["available"], ":digest": item["migrationDigest"], ":capacity": item["capacity"], ":external": "ticketmaster"})
        print("Migration complete. Existing orders, seats and QR codes unchanged.")


if __name__ == "__main__":
    main()
