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


# Music genres used before the platform became an events platform. Older events
# and older survey answers may still contain them; they all count as "music".
LEGACY_MUSIC_GENRES = {
    "pop", "rock", "indie", "electronic", "hip-hop", "reggaeton", "jazz",
    "classical", "r&b", "latin", "catalan",
}


def _normal(text):
    return " ".join(str(text or "").split()).lower()


def category_of(value):
    """The event category for a stored "genre" value (old music genres -> music)."""
    value = _normal(value)
    return "music" if value in LEGACY_MUSIC_GENRES else value


def follows(association, followed):
    """True if the event's association is one the user follows.

    Names are compared ignoring case and spaces, and a followed name may be
    part of the full name ("finance club" matches "ESADE Finance Club").
    """
    name = _normal(association)
    return bool(name) and any(f == name or (len(f) >= 4 and f in name) for f in followed)


def score_event(e, prefs):
    """Simple, explainable score. Easy to describe in the report.

    +3 the event's category is one of the user's interests
    +5 it is published by an association (or held at a venue) the user follows
    +2 it is in the user's city
    +1 the price fits the user's budget (shown as "free entry" when it is free)
    """
    score, why = 0, []
    interests = {category_of(g) for g in prefs.get("genres", [])}
    followed = [_normal(a) for a in prefs.get("favoriteArtists", []) if _normal(a)]
    city = _normal(prefs.get("city", ""))
    max_price = prefs.get("maxPrice")

    category = category_of(e.get("genre"))
    if category and category in interests:
        score += 3
        why.append("you're interested in " + category)
    if follows(e.get("artist"), followed):
        score += 5
        why.append("by " + str(e["artist"]).strip() + ", which you follow")
    if city and _normal(e.get("city")) == city:
        score += 2
        why.append("in " + str(e["city"]).strip())
    price = e.get("price")
    if max_price is not None and price is not None and price <= max_price:
        score += 1
        why.append("free entry" if price == 0 else "fits your budget")
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
    return [{**e, "score": 0, "reasons": ["coming up soon"]} for e in upcoming[:limit]]


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
