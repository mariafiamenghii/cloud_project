"""Artist-only short-lived uploads; public reads only for published associations."""
import base64
import json
import os
import re
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

MAX_BYTES = 5 * 1024 * 1024
TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def response(code, body):
    return {"statusCode": code, "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"}, "body": json.dumps(body)}


def handler(event, context):
    event_id = (event.get("pathParameters") or {}).get("eventId")
    s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
    if event_id:
        item = boto3.resource("dynamodb").Table(os.environ["EVENTS_TABLE"]).get_item(
            Key={"eventId": event_id}, ConsistentRead=True,
            ProjectionExpression="imageObjectKey",
        ).get("Item", {})
        key = item.get("imageObjectKey")
        if key != f"published/{event_id}.webp": return response(404, {"error": "Image not found"})
        try:
            obj = s3.get_object(Bucket=os.environ["IMAGES_BUCKET"], Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404"): return response(404, {"error": "Image not found"})
            raise
        content = obj["Body"].read(3 * 1024 * 1024 + 1)
        if len(content) > 3 * 1024 * 1024: return response(503, {"error": "Image unavailable"})
        return {"statusCode": 200, "isBase64Encoded": True, "body": base64.b64encode(content).decode(),
            "headers": {"Content-Type": "image/webp", "Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff"}}

    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    user = claims.get("sub")
    if not isinstance(user, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", user):
        return response(401, {"error": "Authentication required"})
    groups = str(claims.get("cognito:groups", "")).translate(str.maketrans({c: " " for c in "[],\"'"})).split()
    if not {"artist", "admin"}.intersection(groups): return response(403, {"error": "Only associations can upload images"})
    try:
        body = json.loads(event.get("body") or "{}")
        if not isinstance(body, dict) or set(body) != {"contentType", "size"}: raise ValueError()
        mime, size = body["contentType"], body["size"]
        if mime not in TYPES or type(size) is not int or not 1 <= size <= MAX_BYTES: raise ValueError()
    except (ValueError, TypeError, KeyError):
        return response(400, {"error": "Upload a JPEG, PNG or WebP image up to 5 MB"})
    key = f"uploads/{user}/{uuid.uuid4().hex}.{TYPES[mime]}"
    authorization = s3.generate_presigned_post(Bucket=os.environ["IMAGES_BUCKET"], Key=key,
        Fields={"Content-Type": mime}, Conditions=[{"Content-Type": mime}, ["content-length-range", 1, MAX_BYTES]], ExpiresIn=300)
    return response(200, {**authorization, "key": key, "expiresIn": 300})
