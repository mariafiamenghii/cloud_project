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
    with urllib.request.urlopen(API + "?" + urllib.parse.urlencode(params), timeout=20) as r:
        return json.load(r)


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
    prices = ev.get("priceRanges")
    if prices and prices[0].get("min") is not None:
        item["price"] = Decimal(str(prices[0]["min"]))
    return {k: v for k, v in item.items() if v != ""}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city")
    ap.add_argument("--pages", type=int, default=3, help="pages of 100 events (max 5 here)")
    ap.add_argument("--table", default=os.environ.get("PREFIX", "ticketing") + "-events")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    key = os.environ.get("TM_API_KEY")
    if not key:
        raise SystemExit("Set your key first: export TM_API_KEY=...")
    if args.pages > 5:
        raise SystemExit("Max 5 pages (the free quota is 5000 calls/day, 5 per second)")

    items = []
    for page in range(args.pages):
        data = fetch_page(key, page, args.city)
        found = data.get("_embedded", {}).get("events", [])
        items += [i for i in (convert(e) for e in found) if i]
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
    with table.batch_writer() as batch:
        for i in items:
            batch.put_item(Item=i)
    print(f"loaded {len(items)} events into {args.table}")


if __name__ == "__main__":
    main()
