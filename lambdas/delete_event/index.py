"""Delete an event (artists their own, admins any).

DELETE /events/{eventId}  (requires a Cognito login token, artist or admin group)

An event that already has sales cannot be deleted, because buyers hold tickets
for it. Two checks protect this: no order may exist for the event except
rejected or failed ones, and the delete itself is conditional on the event's
sold and reserved counters being zero, so a purchase that arrives at the same
moment either wins (and the delete is refused) or arrives too late (and the
purchase is refused).
"""

import json
import os

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

_ddb = boto3.resource("dynamodb")
_events = _ddb.Table(os.environ["EVENTS_TABLE"])
_orders = _ddb.Table(os.environ["ORDERS_TABLE"])


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _has_orders(event_id):
    """True if any order other than a rejected or failed one exists for the event."""
    scan = {
        "FilterExpression": Attr("eventId").eq(event_id)
        & ~Attr("orderStatus").is_in(["REJECTED", "FAILED"])
    }
    while True:
        page = _orders.scan(**scan)
        if page.get("Items"):
            return True
        if "LastEvaluatedKey" not in page:
            return False
        scan["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def handler(event, context):
    claims = (
        event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    )
    user_id = claims.get("sub")
    if not isinstance(user_id, str) or not user_id.strip():
        return _response(401, {"error": "Authentication required"})

    # HTTP API turns the group list into a string such as "[artist admin]".
    groups = str(claims.get("cognito:groups", "")).translate(
        str.maketrans({c: " " for c in "[],\"'"})
    ).split()
    is_admin = "admin" in groups
    if "artist" not in groups and not is_admin:
        return _response(403, {"error": "Only artists and admins can delete events"})

    event_id = (event.get("pathParameters") or {}).get("eventId")
    if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 256:
        return _response(400, {"error": "Missing or invalid eventId"})

    item = _events.get_item(Key={"eventId": event_id}, ConsistentRead=True).get("Item")
    if not item:
        return _response(404, {"error": "Event not found"})
    if not is_admin and item.get("artistId") != user_id:
        return _response(403, {"error": "You can only delete your own events"})

    if _has_orders(event_id):
        return _response(409, {"error": "This event already has sales and cannot be deleted"})

    condition = (
        "attribute_exists(eventId) AND "
        "(attribute_not_exists(#sold) OR #sold = :zero) AND "
        "(attribute_not_exists(#reserved) OR #reserved = :zero)"
    )
    names = {"#sold": "sold", "#reserved": "reserved"}
    values = {":zero": 0}
    if not is_admin:
        condition += " AND artistId = :owner"
        values[":owner"] = user_id

    try:
        _events.delete_item(
            Key={"eventId": event_id},
            ConditionExpression=condition,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return _response(409, {"error": "The event changed or has sales. Reload and try again"})
        raise

    return _response(200, {"deleted": event_id})
