"""Explicit live media/genre test using isolated users and new event fixtures.

Tokens and credentials stay in memory; test accounts are disabled afterwards.
Existing events, orders, tickets and inventory are never rewritten by this test.
"""
import argparse
import io
import json
import secrets
import urllib.error
import urllib.request
import uuid
from datetime import date, timedelta

import boto3
from PIL import Image
from test_quantity_live import api, settle


def multipart_upload(authorization, content, mime):
    boundary = "event-image-" + uuid.uuid4().hex
    chunks = []
    for name, value in authorization["fields"].items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="event-image"\r\nContent-Type: {mime}\r\n\r\n'.encode())
    chunks += [content, f"\r\n--{boundary}--\r\n".encode()]
    request = urllib.request.Request(authorization["url"], data=b"".join(chunks),
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    try:
        with urllib.request.urlopen(request, timeout=30) as response: assert response.status in (200, 201, 204)
    except urllib.error.HTTPError as error:
        raise AssertionError(f"Direct S3 upload returned {error.code}") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    parser.add_argument("--api", required=True); parser.add_argument("--pool", required=True); parser.add_argument("--client", required=True)
    args = parser.parse_args()
    cognito = boto3.client("cognito-idp", region_name="us-east-1")
    users, passwords, tokens, event_ids = [], [], [], []
    run_id = uuid.uuid4().hex[:10]; report = {"runId": run_id}
    def login(index):
        return cognito.initiate_auth(ClientId=args.client, AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": users[index], "PASSWORD": passwords[index]})["AuthenticationResult"]["AccessToken"]
    try:
        for index in range(2):
            username = f"media-test-{run_id}-{index}@example.invalid"; password = "Aa9!" + secrets.token_urlsafe(30)
            cognito.admin_create_user(UserPoolId=args.pool, Username=username, MessageAction="SUPPRESS",
                UserAttributes=[{"Name": "email", "Value": username}, {"Name": "email_verified", "Value": "true"}])
            users.append(username); passwords.append(password)
            cognito.admin_set_user_password(UserPoolId=args.pool, Username=username, Password=password, Permanent=True)
            if index == 0: cognito.admin_add_user_to_group(UserPoolId=args.pool, Username=username, GroupName="artist")
            tokens.append(login(index))
        upload_body = {"contentType": "image/png", "size": 100}
        assert api(args.api, "/event-images/uploads", body=upload_body)[0] == 401
        assert api(args.api, "/event-images/uploads", tokens[1], upload_body)[0] == 403
        assert api(args.api, "/event-images/uploads", tokens[0], {"contentType": "image/svg+xml", "size": 100})[0] == 400
        assert api(args.api, "/event-images/uploads", tokens[0], {"contentType": "image/png", "size": 5242881})[0] == 400
        cognito.admin_add_user_to_group(UserPoolId=args.pool, Username=users[1], GroupName="artist"); tokens[1] = login(1)

        def event_body(name):
            return {"name": name + " " + run_id, "artist": "Cloud Lab Test", "city": "Barcelona", "genre": "catalan",
                "date": (date.today() + timedelta(days=30)).isoformat(), "price": 25, "capacity": 100}

        for fmt, mime in (("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")):
            image = io.BytesIO(); Image.new("RGB", (640, 360), (80, 45, 150)).save(image, format=fmt); content = image.getvalue()
            status, auth = api(args.api, "/event-images/uploads", tokens[0], {"contentType": mime, "size": len(content)})
            assert status == 200, (status, auth)
            multipart_upload(auth, content, mime)
            body = {**event_body("Media Test " + fmt), "imageKey": auth["key"]}
            assert api(args.api, "/events", tokens[1], body)[0] == 400
            status, result = api(args.api, "/events", tokens[0], body); assert status == 201, (status, result)
            event_id = result["eventId"]; event_ids.append(event_id)
            url = args.api + "/event-images/" + event_id
            for _ in range(2):
                with urllib.request.urlopen(url) as response:
                    assert response.headers.get_content_type() == "image/webp"
                    with Image.open(io.BytesIO(response.read())) as verified: assert verified.format == "WEBP"
        assert api(args.api, "/events", tokens[0], {**event_body("Invalid external image"), "imageUrl": "https://arbitrary.example/a.jpg"})[0] == 400
        status, result = api(args.api, "/events", tokens[0], event_body("Optional image")); assert status == 201
        report["optionalImageEventId"] = result["eventId"]
        status, events = api(args.api, "/events"); assert status == 200
        for event_id in event_ids:
            item = next(e for e in events if e["eventId"] == event_id)
            assert item["genre"] == "catalan" and item["imageUrl"] == args.api + "/event-images/" + event_id
        status, _ = api(args.api, "/preferences", tokens[0], {"genres": ["catalan"], "favoriteArtists": [], "city": "Barcelona", "maxPrice": 80})
        assert status in (200, 201, 204)
        assert "catalan" in api(args.api, "/preferences", tokens[0])[1]["genres"]
        recommendations = api(args.api, "/recommendations", tokens[0])[1]
        assert any(e["eventId"] in event_ids and e.get("imageUrl") and "you like catalan" in e.get("reasons", []) for e in recommendations)
        ticket_ids, order_ids = [], []
        for quantity in (1, 4):
            status, result = api(args.api, "/purchases", tokens[0], {"eventId": event_ids[0], "quantity": quantity, "idempotencyKey": f"media-{run_id}-{quantity}"})
            assert status == 202, result
            order = settle(args.api, result["orderId"], tokens[0]); assert order["orderStatus"] == "CONFIRMED"
            assert len(order["tickets"]) == quantity
            ticket_ids.extend(t["ticketId"] for t in order["tickets"]); order_ids.append(order["orderId"])
        assert len(set(ticket_ids)) == 5
        _, inventory = api(args.api, f"/events/{event_ids[0]}/inventory")
        assert inventory["sold"] == 5 and inventory["available"] == 95 and inventory["reserved"] == 0
        report.update(result="PASS", imageFormats=["JPEG", "PNG", "WEBP"], imageEventIds=event_ids,
            catalanPreferencesAndRecommendations=True, orderIds=order_ids, uniqueTickets=5, sold=5, available=95)
    finally:
        for username in users: cognito.admin_disable_user(UserPoolId=args.pool, Username=username)
        report["disabledTestUsers"] = len(users)
        print(json.dumps(report, indent=2))


if __name__ == "__main__": main()
