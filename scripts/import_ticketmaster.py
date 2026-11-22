"""Import real concerts in Spain from the official Ticketmaster Discovery API (plan A).

Needs a free API key from https://developer.ticketmaster.com (set TM_API_KEY).
Imported events keep source="ticketmaster" and an externalUrl: tickets for them
are NOT sold in our app, the user is sent to the official seller.

Usage (from the repo root):
  export TM_API_KEY=...            # never commit it
  python3 scripts/import_ticketmaster.py --dry-run     # only print what it would load
  python3 scripts/import_ticketmaster.py               # load into DynamoDB
Options: --city Barcelona  --pages 3  --table ticketing-events
"""
import argparse
import json
import os
import time
import urllib.parse
import urllib.request
import uuid
from decimal import Decimal
from pathlib import Path
from ticketmaster_media import Discovery, metadata, safe_update

API = "https://app.ticketmaster.com/discovery/v2/events.json"


def fetch_page(key, page, city=None, size=100):
    params = {
        "apikey": key,
        "countryCode": "ES",
        "classificationName": "music",
        "size": size,
        "page": page,
        "sort": "date,asc",
    }
    if city:
        params["city"] = city
    params.pop("apikey")
    return Discovery(key).get("events.json", **params)


def convert(ev):
    """Map one Ticketmaster event to our table format. Returns None if unusable."""
    emb = ev.get("_embedded", {})
    venues = emb.get("venues") or [{}]
    attractions = emb.get("attractions") or [{}]
    date = ev.get("dates", {}).get("start", {}).get("localDate")
    if not date or not ev.get("name"):
        return None
    cls = (ev.get("classifications") or [{}])[0]
    genre = (cls.get("genre") or {}).get("name", "")
    item = {
        "eventId": str(uuid.uuid5(uuid.NAMESPACE_URL, "ticketmaster|" + ev["id"])),
        "artistId": "ticketmaster-import",
        "name": ev["name"],
        "artist": attractions[0].get("name", ev["name"]),
        "genre": genre.lower() if genre and genre.lower() != "undefined" else "",
        "city": venues[0].get("city", {}).get("name", ""),
        "venue": venues[0].get("name", ""),
        "date": date,
        "capacity": 0,  # we do not sell these tickets
        "source": "ticketmaster",
        "externalUrl": ev.get("url", ""),
        "createdAt": int(time.time()),
    }
    item.update(metadata(ev))
    return {k: v for k, v in item.items() if v != ""}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city")
    ap.add_argument("--pages", type=int, default=3, help="pages of 100 events (max 5 here)")
    ap.add_argument("--table", default=os.environ.get("PREFIX", "ticketing") + "-events")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--backfill", action="store_true", help="Metadata-only update of existing imported records; dry-run unless --apply")
    ap.add_argument("--apply", action="store_true", help="Apply a reviewed metadata backfill")
    ap.add_argument("--key-file", help="Read the API key securely from a local file")
    args = ap.parse_args()

    key = Path(args.key_file).read_text().strip() if args.key_file else os.environ.get("TM_API_KEY")
    if not key:
        raise SystemExit("Set your key first: export TM_API_KEY=...")
    if args.backfill:
        return backfill(args, Discovery(key))
    if args.pages > 5:
        raise SystemExit("Max 5 pages (the free quota is 5000 calls/day, 5 per second)")

    items = []
    client = Discovery(key)
    for page in range(args.pages):
        data = client.get("events.json", countryCode="ES", classificationName="music", size=100,
                          page=page, sort="date,asc", **({"city": args.city} if args.city else {}))
        found = data.get("_embedded", {}).get("events", [])
        items += [i for i in (convert(client.enrich(e)) for e in found) if i]
        if page + 1 >= data.get("page", {}).get("totalPages", 0):
            break
        time.sleep(0.3)  # stay under 5 requests/second

    print(f"{len(items)} events converted")
    for i in items[:5]:
        print(" ", i["date"], i.get("artist"), "-", i.get("city"), "-", i.get("genre") or "?")
    if args.dry_run:
        print("dry run: nothing written")
        return

    import boto3

    table = boto3.resource("dynamodb").Table(args.table)
    from botocore.exceptions import ClientError
    for item in items:
        try:
            table.put_item(Item=item, ConditionExpression="attribute_not_exists(eventId)")
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException": raise
            existing = table.get_item(Key={"eventId": item["eventId"]}, ConsistentRead=True)["Item"]
            safe_update(table, existing, {k: v for k, v in item.items() if k in {"imageUrl", "imageAttribution", "imageWidth", "imageHeight", "imageFallback", "price", "currency", "ticketmasterId"}})
    print(f"loaded {len(items)} events into {args.table}")


def backfill(args, client):
    import boto3
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(args.table)
    records, params = [], {"ConsistentRead": True}
    while True:
        page = table.scan(**params); records.extend(page.get("Items", []))
        if not page.get("LastEvaluatedKey"): break
        params["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    records = [r for r in records if r.get("source") == "ticketmaster"]
    known = {}
    for city in sorted({r.get("city") for r in records if r.get("city")}):
        for event in client.events(city):
            known[str(uuid.uuid5(uuid.NAMESPACE_URL, "ticketmaster|" + event["id"]))] = event
    report = {"records": len(records), "imagesUpdated": 0, "imagesSkipped": 0, "imagesUnavailable": 0, "pricesUpdated": 0, "pricesUnavailable": 0, "conflicts": 0, "apply": bool(args.apply and not args.dry_run)}
    for existing in records:
        event = known.get(existing["eventId"])
        if event is None and existing.get("ticketmasterId"):
            event = client.get("events/" + urllib.parse.quote(existing["ticketmasterId"], safe="") + ".json")
        if not event:
            report["imagesUnavailable"] += 1; report["pricesUnavailable"] += 1
            continue
        updates = metadata(client.enrich(event))
        if "imageUrl" not in updates:
            report["imagesUnavailable"] += 1
        elif existing.get("imageUrl") == updates["imageUrl"]:
            report["imagesSkipped"] += 1
        else: report["imagesUpdated"] += 1
        if "price" not in updates: report["pricesUnavailable"] += 1
        elif (existing.get("price"), existing.get("currency")) != (updates["price"], updates["currency"]): report["pricesUpdated"] += 1
        updates["ticketmasterUpdatedAt"] = int(time.time())
        if report["apply"]:
            from botocore.exceptions import ClientError
            try: safe_update(table, existing, updates)
            except ClientError as error:
                if error.response["Error"]["Code"] != "ConditionalCheckFailedException": raise
                report["conflicts"] += 1
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
