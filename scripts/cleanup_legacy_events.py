"""Remove legacy events from the events table. Read-only unless --apply is given.

Run from the repo root:   python3 scripts/cleanup_legacy_events.py            (report only)
                          python3 scripts/cleanup_legacy_events.py --apply    (deletes)

Legacy events are:
- every Ticketmaster import (source "ticketmaster"),
- old sample events (source "sample") that are not in the current
  data/sample_events.json (old concerts and earlier association samples),
- old Barcelona imports (source "barcelona_open_data") whose genre is not one
  of CATEGORIES (for example "jazz", "rock" or empty).

The current sample events and Barcelona imports are kept, so the script can run
before or after scripts/load_events.py (after is clearer: the report then lists
exactly the old samples).
Events published by associations (no source or source "internal") and events
with any other source are never deleted. An event is also kept if it has any
order (of any status), any row in the legacy seats table, or sold/reserved
tickets. The delete itself is conditional, so an event that changed after the
scan is left untouched. Orders, seats and tickets are never modified.
"""
import argparse
import importlib.util
import json
import uuid
from collections import Counter
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]


def load_categories():
    spec = importlib.util.spec_from_file_location(
        "event_categories", ROOT / "lambdas/create_event/categories.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return set(module.CATEGORIES)


def current_sample_ids():
    """Event ids that scripts/load_events.py gives the current sample events (same formula)."""
    events = json.loads((ROOT / "data/sample_events.json").read_text(encoding="utf-8"))
    return {str(uuid.uuid5(uuid.NAMESPACE_URL, f"{e['artist']}|{e['date']}|{e['venue']}")) for e in events}


CATEGORIES = load_categories()
CURRENT_SAMPLE_IDS = current_sample_ids()
ALWAYS_LEGACY = {"ticketmaster"}
LEGACY_IF_OLD_GENRE = {"barcelona_open_data"}
KNOWN_SOURCES = ALWAYS_LEGACY | LEGACY_IF_OLD_GENRE | {"sample", "internal"}


def scan(table):
    page = table.scan(ConsistentRead=True)
    items = page.get("Items", [])
    while page.get("LastEvaluatedKey"):
        page = table.scan(ConsistentRead=True, ExclusiveStartKey=page["LastEvaluatedKey"])
        items.extend(page.get("Items", []))
    return items


def genre_of(event):
    return str(event.get("genre") or "").strip().lower()


def is_legacy(event):
    source = event.get("source") or ""
    if source in ALWAYS_LEGACY:
        return True
    if source == "sample":
        return event["eventId"] not in CURRENT_SAMPLE_IDS
    return source in LEGACY_IF_OLD_GENRE and genre_of(event) not in CATEGORIES


def has_seats(seats, event_id):
    page = seats.query(KeyConditionExpression=Key("eventId").eq(event_id), Limit=1, ConsistentRead=True)
    return bool(page.get("Items"))


def plan(events, orders, seats):
    """Split legacy events into (delete, keep_with_reason). Non-legacy events are ignored."""
    ordered = {order.get("eventId") for order in orders}
    delete, keep = [], []
    for event in events:
        if not is_legacy(event):
            continue
        event_id = event["eventId"]
        if event_id in ordered:
            keep.append((event, "has orders"))
        elif event.get("sold", 0) or event.get("reserved", 0):
            keep.append((event, "has sold or reserved tickets"))
        elif has_seats(seats, event_id):
            keep.append((event, "has seat records"))
        else:
            delete.append(event)
    return delete, keep


def delete_event(table, event):
    """Delete only if the event still has the same source and no sold/reserved tickets."""
    try:
        table.delete_item(
            Key={"eventId": event["eventId"]},
            ConditionExpression=(
                "attribute_exists(eventId) AND #source = :source AND "
                "(attribute_not_exists(#sold) OR #sold = :zero) AND "
                "(attribute_not_exists(#reserved) OR #reserved = :zero)"
            ),
            ExpressionAttributeNames={"#source": "source", "#sold": "sold", "#reserved": "reserved"},
            ExpressionAttributeValues={":source": event["source"], ":zero": 0},
        )
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def print_report(events, delete, keep):
    print(f"Events in table: {len(events)}")
    print(f"Legacy events to delete: {len(delete)}")
    for title, key in (("By source", lambda e: e.get("source") or "(none)"),
                       ("By genre", lambda e: genre_of(e) or "(none)")):
        print(f"  {title}:")
        for value, count in sorted(Counter(key(e) for e in delete).items()):
            print(f"    {value}: {count}")
    if keep:
        print(f"Legacy events kept for safety: {len(keep)}")
        for event, reason in keep:
            print(f"    {event['eventId']} ({event.get('source')}, {event.get('name', '')}): {reason}")
    others = Counter(e.get("source") for e in events
                     if (e.get("source") or "internal") not in KNOWN_SOURCES)
    if others:
        print(f"Events with an unknown source (never deleted): {dict(others)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="really delete (default: report only)")
    parser.add_argument("--prefix", default="ticketing")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    ddb = boto3.Session(region_name=args.region).resource("dynamodb")
    events_table = ddb.Table(f"{args.prefix}-events")
    events = scan(events_table)
    orders = scan(ddb.Table(f"{args.prefix}-orders"))
    delete, keep = plan(events, orders, ddb.Table(f"{args.prefix}-seats"))
    print_report(events, delete, keep)

    if not args.apply:
        print("Report only. Nothing was deleted. Run again with --apply to delete.")
        return
    deleted = sum(delete_event(events_table, event) for event in delete)
    print(f"Deleted {deleted} events. Skipped {len(delete) - deleted} that changed since the scan.")


if __name__ == "__main__":
    main()
