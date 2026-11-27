"""Import events from the Barcelona city cultural agenda (Open Data BCN) into DynamoDB.

This is the "city of Barcelona" source, next to the ESADE events published in
the app. It replaces the Ticketmaster import. No API key needed:
the City Council publishes the agenda as open data (JSON, updated daily).
Imported events keep source="barcelona_open_data" and an externalUrl (when the
agenda gives one): tickets are NOT sold in our app, the user is sent to the
official page. Open data requires citing the source, so every image carries an
attribution line.

Events are mapped to our categories (music, festivals, food, workshops, art,
talks, theatre, family, sports, tech, sustainability); events in none of them
are skipped. Each category keeps its soonest events, up to a cap, so the home
page is a mix (music has a lower cap because concerts are most of the agenda).

Usage (from the repo root):
  python3 scripts/import_bcn_agenda.py --dry-run          # download and print only
  python3 scripts/import_bcn_agenda.py                    # load into DynamoDB
Options: --file /tmp/agenda.json (reuse a downloaded copy)  --per-category 20
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

# City Council category names (Catalan, lowercase) -> our event category.
# Every category here must be in CATEGORIES (web/src/utils/eventMedia.ts and
# lambdas/create_event/categories.py); tests/test_bcn_agenda.py checks it.
# A needle matches a category name exactly, or as a substring when it has 4 or
# more characters. The first rule that matches wins, so order matters: specific
# topics come before broad ones ("a cooking workshop" is food, "a museum talk" is
# a talk). A concert is always music, even in a theatre or for children.
CONCERT = "concerts"
CATEGORY_RULES = [
    ("food", ("cuina", "gastronom", "degustacions", "menjars", "alimentació")),
    ("sustainability", ("sostenibilitat", "medi ambient", "ecologia", "cooperació i solidaritat",
                        "voluntariat")),
    ("tech", ("tecnologi", "informàtica", "steam")),
    ("sports", ("esport", "caminada", "cursa", "bicicleta", "ioga")),
    ("workshops", ("cursos i tallers", "tallers", "artesania", "manualitats", "treballs manuals")),
    # Festivals include Christmas (Nadal): parades, fairs, nativity scenes.
    ("festivals", ("festivals", "festes populars", "festa major", "festes", "cercaviles",
                   "cavalcades", "tradicions populars", "nadal")),
    ("talks", ("col·loquis", "xerrades", "conferències", "debats", "taules rodones", "tertúlies",
               "presentacions", "literatura", "filosofia")),
    ("theatre", ("teatre", "espectacles", "dansa", "performances")),
    ("art", ("exposicions", "fotografia", "dibuix", "pintura", "disseny", "arquitectura",
             "instal·lacions", "arts digitals", "cinema", "projeccions", "documentals", "museus")),
    # Nightlife (DJs, clubs) is listed under music.
    ("music", ("música", "jazz", "pop", "rock", "hip-hop", "flamenc", "cant coral", "cantautors",
               "òpera", "rumba", "orquestra", "simfònic", "discjòqueis", "vida nocturna",
               "discoteques", "instruments musicals")),
    ("family", ("activitats per a infants", "famílies", "contes", "nens i nenes")),
]


def class_names(record):
    return [str(c.get("name", "")).strip().lower() for c in (record.get("classifications_data") or [])]


def _matches(needle, names):
    return any(name == needle or (len(needle) >= 4 and needle in name) for name in names)


def category_for(names):
    """Our category for the agenda's category names, or "" if none applies."""
    if CONCERT in names:
        return "music"
    for category, needles in CATEGORY_RULES:
        if any(_matches(needle, names) for needle in needles):
            return category
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
    category = category_for(class_names(record))
    if not category:
        return None  # not in one of our categories
    address = (record.get("addresses") or [{}])[0]
    place = str(address.get("place") or "").strip()
    key = str(record.get("register_id") or name + "|" + start)
    item = {
        "eventId": str(uuid.uuid5(uuid.NAMESPACE_URL, "bcn-agenda|" + key)),
        "artistId": "barcelona-open-data-import",
        "name": name,
        "artist": place or "Barcelona",
        "genre": category,  # the category is stored in the "genre" field
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


# Music is most of the agenda (concerts), so it gets a lower cap to keep the
# home page a mix of categories. Other categories use --per-category.
CATEGORY_CAPS = {"music": 15}


def pick(records, today, per_category, caps=None):
    """Convert, keep the soonest events and at most a cap per category (mix of topics).

    A show repeated on several days has one record per day; only the soonest is
    kept, so the home page does not list the same event name several times.
    """
    caps = CATEGORY_CAPS if caps is None else caps
    items = [i for i in (convert(r, today) for r in records) if i]
    items.sort(key=lambda i: (i["date"], i["name"]))
    seen, names, counts, chosen = set(), set(), Counter(), []
    for item in items:
        group = item["genre"]
        name = " ".join(item["name"].split()).casefold()
        if item["eventId"] in seen or name in names:
            continue
        if counts[group] >= min(per_category, caps.get(group, per_category)):
            continue
        seen.add(item["eventId"])
        names.add(name)
        counts[group] += 1
        chosen.append(item)
    return chosen


def load_records(path):
    if path and Path(path).exists():
        return json.loads(Path(path).read_bytes())  # bytes: UTF-8 on every OS
    print("Downloading the agenda (about 180 MB, can take a minute)...")
    request = urllib.request.Request(DATA_URL, headers={"User-Agent": "front-row-student-project"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="Path of an already downloaded agenda JSON")
    # --per-genre is the old name of the option, kept so old commands still work.
    ap.add_argument("--per-category", "--per-genre", dest="per_category", type=int, default=20)
    ap.add_argument("--table", default=os.environ.get("PREFIX", "ticketing") + "-events")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    today = datetime.date.today().isoformat()
    items = pick(load_records(args.file), today, args.per_category)
    by_category = Counter(i["genre"] for i in items)
    print(f"{len(items)} events selected:", dict(by_category.most_common()))
    for category in by_category:
        first = next(i for i in items if i["genre"] == category)
        print(f"  {category:15s} e.g. {first['date']} {first['name'][:55]}")
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
