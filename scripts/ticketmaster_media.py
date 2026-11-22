"""Official Discovery API metadata only; never download/rehost provider images."""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation

API = "https://app.ticketmaster.com/discovery/v2/"
MEDIA_FIELDS = {"ticketmasterId", "imageUrl", "imageAttribution", "imageWidth", "imageHeight", "imageFallback", "price", "currency", "ticketmasterUpdatedAt"}


def metadata(event):
    result = {"ticketmasterId": event["id"]} if event.get("id") else {}
    images = [im for im in event.get("images", []) if isinstance(im, dict) and str(im.get("url", "")).startswith("https://")]
    def rank(im):
        width, height = im.get("width", 0), im.get("height", 0)
        width = width if isinstance(width, (int, float)) else 0
        height = height if isinstance(height, (int, float)) else 0
        ratio = width / height if height > 0 else 0
        return (not im.get("fallback", False), ratio > 1, -abs(ratio - 16 / 9), min(width, 1280), -abs(width - 1280))
    if images:
        image = max(images, key=rank)
        result.update(imageUrl=image["url"], imageFallback=bool(image.get("fallback", False)))
        for field in ("width", "height"):
            if type(image.get(field)) is int and image[field] > 0:
                result["image" + field.title()] = image[field]
        if image.get("attribution"):
            result["imageAttribution"] = str(image["attribution"])[:1000]
    prices = {}
    for price in event.get("priceRanges") or []:
        if not isinstance(price, dict) or isinstance(price.get("min"), bool):
            continue
        currency = str(price.get("currency", "")).upper()
        try:
            amount = Decimal(str(price.get("min")))
        except InvalidOperation:
            continue
        if re.fullmatch(r"[A-Z]{3}", currency) and amount.is_finite() and amount >= 0:
            prices[currency] = min(amount, prices.get(currency, amount))
    if prices:
        currency = "EUR" if "EUR" in prices else sorted(prices)[0]
        result.update(price=prices[currency], currency=currency)
    return result


class Discovery:
    def __init__(self, key):
        self.key = key
        self.last_request = 0

    def get(self, path, **params):
        for attempt in range(3):
            time.sleep(max(0, 0.27 - (time.monotonic() - self.last_request)))
            url = API + path + "?" + urllib.parse.urlencode({**params, "apikey": self.key})
            self.last_request = time.monotonic()
            try:
                with urllib.request.urlopen(url, timeout=20) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code in (404, 410): return {}
                if error.code == 429 and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"Ticketmaster API returned HTTP {error.code}") from None
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2: raise RuntimeError("Ticketmaster API could not be reached") from None
        return {}

    def events(self, city=None, pages=10):
        for page in range(pages):
            data = self.get("events.json", countryCode="ES", classificationName="music", size=100,
                            page=page, sort="date,asc", **({"city": city} if city else {}))
            yield from data.get("_embedded", {}).get("events", [])
            if page + 1 >= data.get("page", {}).get("totalPages", 0): break

    def enrich(self, event):
        value = dict(event)
        current = metadata(value)
        event_id = urllib.parse.quote(value["id"], safe="")
        if "imageUrl" not in current or "price" not in current:
            details = self.get(f"events/{event_id}.json")
            # Missing detail fields must not discard valid search metadata.
            if details.get("images"): value["images"] = details["images"]
            if details.get("priceRanges"): value["priceRanges"] = details["priceRanges"]
        if "imageUrl" not in metadata(value):
            value["images"] = self.get(f"events/{event_id}/images.json").get("images", [])
        return value


def safe_update(table, existing, updates):
    """Metadata-only CAS update. Never replace records or overwrite inventory."""
    assert set(updates) <= MEDIA_FIELDS
    updates = {k: v for k, v in updates.items() if existing.get(k) != v}
    if not updates: return False
    names = {"#source": "source"}
    values = {":source": "ticketmaster"}
    expressions = []
    conditions = ["attribute_exists(eventId)", "#source = :source"]
    for index, (key, value) in enumerate(updates.items()):
        name, token, old = f"#f{index}", f":v{index}", f":old{index}"
        names[name] = key; values[token] = value
        expressions.append(f"{name} = {token}")
        if key in existing:
            values[old] = existing[key]; conditions.append(f"{name} = {old}")
        else:
            conditions.append(f"attribute_not_exists({name})")
    table.update_item(Key={"eventId": existing["eventId"]}, UpdateExpression="SET " + ", ".join(expressions),
        ConditionExpression=" AND ".join(conditions), ExpressionAttributeNames=names, ExpressionAttributeValues=values)
    return True
