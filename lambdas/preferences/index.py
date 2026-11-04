import json
import os
import time
from decimal import Decimal

import boto3

table = boto3.resource("dynamodb").Table(os.environ["PREFS_TABLE"])


def _default(o):
    if isinstance(o, Decimal):
        return int(o) if o % 1 == 0 else float(o)
    raise TypeError


def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=_default),
    }


def _clean_list(value):
    """Keep at most 20 short, non-empty strings."""
    if not isinstance(value, list):
        return []
    out = []
    for v in value:
        s = str(v).strip()
        if s and len(s) <= 60:
            out.append(s)
    return out[:20]


def handler(event, context):
    # API Gateway already checked the login token. We use the user id inside it.
    user = event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
    method = event["requestContext"]["http"]["method"]

    if method == "GET":
        item = table.get_item(Key={"userId": user}).get("Item")
        return _resp(200, item or {"userId": user, "genres": [], "favoriteArtists": [], "city": ""})

    # POST: save the taste survey
    try:
        data = json.loads(event.get("body") or "{}", parse_float=Decimal)
    except ValueError:
        return _resp(400, {"error": "Body must be valid JSON"})

    item = {
        "userId": user,
        "genres": [g.lower() for g in _clean_list(data.get("genres"))],
        "favoriteArtists": _clean_list(data.get("favoriteArtists")),
        "city": str(data.get("city", "")).strip()[:60],
        "updatedAt": int(time.time()),
    }

    max_price = data.get("maxPrice")
    if max_price is not None:
        ok = isinstance(max_price, (int, Decimal)) and not isinstance(max_price, bool) and max_price >= 0
        if not ok:
            return _resp(400, {"error": "maxPrice must be a number >= 0"})
        item["maxPrice"] = max_price

    table.put_item(Item=item)
    return _resp(200, item)
