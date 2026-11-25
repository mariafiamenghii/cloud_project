"""Import events from the Barcelona city cultural agenda (Open Data BCN) into DynamoDB.

Replaces the Ticketmaster import as the "outside ESADE" source. No API key needed:
the City Council publishes the agenda as open data (JSON, updated daily).
Imported events keep source="barcelona_open_data" and an externalUrl (when the
agenda gives one): tickets are NOT sold in our app, the user is sent to the
official page. Open data requires citing the source, so every image carries an
attribution line.

Usage (from the repo root):
  python3 scripts/import_bcn_agenda.py --dry-run          # download and print only
  python3 scripts/import_bcn_agenda.py                    # load into DynamoDB
Options: --file /tmp/agenda.json (reuse a downloaded copy)  --per-genre 30
         --table ticketing-events
"""
import argparse
import datetime
import json
import os
import time
import urllib.request
import uuid
from collections import Counter
from pathlib import Path

DATA_URL = ("https://opendata-ajuntament.barcelona.cat/data/dataset/"
            "2767159c-1c98-46b8-a686-2b25b40cb053/resource/"
            "59b9c807-f6c1-4c10-ac51-1ace65485079/download")
SOURCE = "barcelona_open_data"
ATTRIBUTION = "Image: Ajuntament de Barcelona (Open Data BCN)"

# City Council category -> genre of our web. First match wins, so order matters.
GENRE_RULES = [
    ("jazz", "jazz"),
    ("música clàssica", "classical"),
    ("concerts simfònics", "classical"),
    ("orquestra", "classical"),
    ("cant coral", "classical"),
    ("música contemporània", "classical"),
    ("música electrònica", "electronic"),
    ("independent", "indie"),
    ("cantautors", "indie"),
    ("hip-hop", "hip-hop"),
    ("flamenc", "latin"),
    ("pop", "pop"),
    ("rock", "rock"),
    ("teatre", "theatre"),
    ("espectacles", "theatre"),
    ("exposicions", "art"),
    ("fotografia", "art"),
    ("dibuix", "art"),
    ("col·loquis", "talks"),
    ("conferències", "talks"),
    ("activitats per a infants i per a famílies", "family"),
]
MUSIC_NAMES = {"concerts", "música"}
NON_MUSIC_GENRES = {"theatre", "art", "talks", "family"}


def class_names(record):
    return [str(c.get("name", "")).strip().lower() for c in (record.get("classifications_data") or [])]


def genre_for(names):
    for needle, genre in GENRE_RULES:
        if any(name == needle or (len(needle) >= 4 and needle in name) for name in names):
            return genre
    return ""


def ticket_url(record):
    """Official page: the ticket-selling site if given, else the plain web, else the venue page."""
    wanted = ("web venda d'entrades", "web")
    found = {}
    for category in record.get("attribute_categories") or []:
        for attr in category.get("attributes") or []:
            name = str(attr.get("name", "")).strip().lower()
            for value in attr.get("values") or []:
                if name in wanted and isinstance(value.get("value"), str):
                    found.setdefault(name, value["value"].strip())
    candidates = [found.get(w) for w in wanted]
    address = (record.get("addresses") or [{}])[0]
    candidates.append(((address.get("related_entity_data") or {}).get("canonical_url")))
    for url in candidates:
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return url
    return ""


def city_name(address):
    """The agenda writes the city as both "Barcelona" and "BARCELONA"; store one spelling."""
    town = " ".join(str(address.get("town") or "").split())
    return "Barcelona" if not town or town.lower() == "barcelona" else town


def ticket_types(record):
    """Entry types the agenda gives ("Lliure" = free entry, "Inscripcions" = sign-up...)."""
    return [str(t.get("name", "")).strip().lower() for t in (record.get("tickets_data") or [])]


def convert(record, today):
    """Map one agenda record to our table format. Returns None if it is not usable."""
    name = str(record.get("name") or "").strip()
    start = str(record.get("start_date") or "")[:10]
    image = record.get("image_data") or {}
    image_url = image.get("image_optimized") or image.get("image") or ""
    if not name or start < today or not image_url.startswith("https://"):
        return None
    names = class_names(record)
    genre = genre_for(names)
    if genre in NON_MUSIC_GENRES and "concerts" in names:
        genre = ""  # a concert in a theatre is still a concert
    if not genre and not MUSIC_NAMES.intersection(names):
        return None  # not music and not in one of our categories
    address = (record.get("addresses") or [{}])[0]
    place = str(address.get("place") or "").strip()
    key = str(record.get("register_id") or name + "|" + start)
    item = {
        "eventId": str(uuid.uuid5(uuid.NAMESPACE_URL, "bcn-agenda|" + key)),
        "artistId": "barcelona-open-data-import",
        "name": name,
        "artist": place or "Barcelona",
        "genre": genre,
        "city": city_name(address),
        "venue": place,
        "date": start,
        "capacity": 0,  # we do not sell these tickets
        **({"price": 0, "currency": "EUR"} if "lliure" in ticket_types(record) else {}),
        "source": SOURCE,
        "externalUrl": ticket_url(record),
        "imageUrl": image_url,
        "imageAttribution": ATTRIBUTION,
        "createdAt": int(time.time()),
    }
    return {k: v for k, v in item.items() if v != ""}


def pick(records, today, per_genre):
    """Convert, keep the soonest events and at most per_genre per genre (mix of categories)."""
    items = [i for i in (convert(r, today) for r in records) if i]
    items.sort(key=lambda i: (i["date"], i["name"]))
    seen, counts, chosen = set(), Counter(), []
    for item in items:
        group = item.get("genre", "music")
        if item["eventId"] in seen or counts[group] >= per_genre:
            continue
        seen.add(item["eventId"])
        counts[group] += 1
        chosen.append(item)
    return chosen


def load_records(path):
    if path and Path(path).exists():
        return json.loads(Path(path).read_text())
    print("Downloading the agenda (about 180 MB, can take a minute)...")
    request = urllib.request.Request(DATA_URL, headers={"User-Agent": "front-row-student-project"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="Path of an already downloaded agenda JSON")
    ap.add_argument("--per-genre", type=int, default=30)
    ap.add_argument("--table", default=os.environ.get("PREFIX", "ticketing") + "-events")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    today = datetime.date.today().isoformat()
    items = pick(load_records(args.file), today, args.per_genre)
    by_genre = Counter(i.get("genre") or "(no genre)" for i in items)
    print(f"{len(items)} events selected:", dict(by_genre))
    for i in items[:5]:
        print(" ", i["date"], i["name"][:60], "-", i.get("venue", ""), "-", i.get("genre") or "?")
    if args.dry_run:
        print("dry run: nothing written")
        return

    import boto3

    table = boto3.resource("dynamodb", region_name="us-east-1").Table(args.table)
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
    print(f"loaded {len(items)} events into {args.table}")


if __name__ == "__main__":
    main()
