"""Decode and canonicalize owned uploads before making an event association."""
import io
import os
import re
import warnings

import boto3

MAX_BYTES = 5 * 1024 * 1024
TYPES = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


def publish_image(key, user, event_id):
    from PIL import Image, ImageOps, UnidentifiedImageError
    if not isinstance(key, str) or not re.fullmatch(r"uploads/" + re.escape(user) + r"/[a-f0-9]{32}\.(jpg|png|webp)", key):
        raise ValueError("Upload an image owned by your account")
    s3 = boto3.client("s3")
    bucket = os.environ["IMAGES_BUCKET"]
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
    except s3.exceptions.NoSuchKey:
        raise ValueError("Image upload is missing; upload the file again") from None
    if obj["ContentLength"] > MAX_BYTES or obj.get("ContentType") not in TYPES:
        raise ValueError("Upload a JPEG, PNG or WebP image up to 5 MB")
    raw = obj["Body"].read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES: raise ValueError("Image exceeds the upload limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as original:
                if original.format != TYPES[obj["ContentType"]] or original.width * original.height > 16_000_000:
                    raise ValueError("Unsupported image format or excessive dimensions")
                original.verify()
            with Image.open(io.BytesIO(raw)) as original:
                original.load()
                image = ImageOps.exif_transpose(original).convert("RGB" if original.mode != "RGBA" else "RGBA")
                image.thumbnail((1600, 1600))
                output = io.BytesIO(); image.save(output, format="WEBP", quality=85)
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ValueError("The uploaded file is not a valid supported image") from None
    content = output.getvalue()
    if len(content) > 3 * 1024 * 1024: raise ValueError("Image is too complex; choose a smaller image")
    target = f"published/{event_id}.webp"
    s3.put_object(Bucket=bucket, Key=target, Body=content, ContentType="image/webp")
    return target


def discard(key):
    # Best-effort cleanup; an orphan remains private and unassociated if S3 fails.
    try: boto3.client("s3").delete_object(Bucket=os.environ["IMAGES_BUCKET"], Key=key)
    except Exception: pass
