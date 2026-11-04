import datetime
import json
import os
from decimal import Decimal

import boto3

_ddb = boto3.resource("dynamodb")


def _default(o):
    if isinstance(o, Decimal):
        return int(o) if o % 1 == 0 else float(o)
    raise TypeError


def _scan_all(table):
    items, kwargs = [], {}
    while True:
        page = table.scan(**kwargs)
        items += page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def score_event(e, prefs):
    """Simple, explainable score. Easy to describe in the report."""
    score, why = 0, []
    genres = [str(g).lower() for g in prefs.get("genres", [])]
    artists = [str(a).lower() for a in prefs.get("favoriteArtists", [])]
    city = str(prefs.get("city", "")).lower()
    max_price = prefs.get("maxPrice")

    if str(e.get("genre", "")).lower() in genres:
        score += 3
        why.append("you like " + str(e["genre"]))
    if str(e.get("artist", "")).lower() in artists:
        score += 5
        why.append("one of your favourite artists")
    if city and str(e.get("city", "")).lower() == city:
        score += 2
        why.append("in " + str(e["city"]))
    if max_price is not None and e.get("price") is not None and e["price"] <= max_price:
        score += 1
        why.append("fits your budget")
    return score, why


def recommend(events, prefs, today, limit=10):
    upcoming = [e for e in events if str(e.get("date", "")) >= today]
    scored = []
    for e in upcoming:
        s, why = score_event(e, prefs)
        if s > 0:
            scored.append({**e, "score": s, "reasons": why})
    scored.sort(key=lambda e: (-e["score"], str(e.get("date", ""))))
    if scored:
        return scored[:limit]
    # No survey yet (or no match): show the soonest events.
    upcoming.sort(key=lambda e: str(e.get("date", "")))
    return [{**e, "score": 0, "reasons": ["upcoming"]} for e in upcoming[:limit]]


def handler(event, context):
    user = event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
    prefs_table = _ddb.Table(os.environ["PREFS_TABLE"])
    events_table = _ddb.Table(os.environ["EVENTS_TABLE"])

    prefs = prefs_table.get_item(Key={"userId": user}).get("Item") or {}
    today = datetime.date.today().isoformat()
    result = recommend(_scan_all(events_table), prefs, today)
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(result, default=_default),
    }
