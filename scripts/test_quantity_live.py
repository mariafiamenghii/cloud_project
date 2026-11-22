"""Explicit live test: creates isolated test users/events/orders; never deletes data.

Requires --run and AWS permissions for Cognito test-user administration. Passwords
and tokens exist only in memory. Both test users are disabled in finally.
"""
import argparse
import json
import secrets
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import boto3


def api(base, path, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(base + path, headers=headers,
        data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def settle(base, order_id, token):
    for _ in range(60):
        code, order = api(base, "/orders/" + order_id, token)
        if code == 200 and order.get("orderStatus") in ("CONFIRMED", "REJECTED", "FAILED", "REVIEW_REQUIRED"):
            return order
        time.sleep(1)
    raise AssertionError("Order did not settle: " + order_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    parser.add_argument("--api", required=True)
    parser.add_argument("--pool", required=True)
    parser.add_argument("--client", required=True)
    args = parser.parse_args()
    cognito = boto3.client("cognito-idp", region_name="us-east-1")
    users, tokens = [], []
    run_id = uuid.uuid4().hex[:12]
    report = {"runId": run_id}
    try:
        for index in range(2):
            username = f"quantity-test-{run_id}-{index}@example.invalid"
            password = "Aa9!" + secrets.token_urlsafe(30)
            cognito.admin_create_user(UserPoolId=args.pool, Username=username, MessageAction="SUPPRESS",
                UserAttributes=[{"Name": "email", "Value": username}, {"Name": "email_verified", "Value": "true"}])
            users.append(username)
            cognito.admin_set_user_password(UserPoolId=args.pool, Username=username, Password=password, Permanent=True)
            if index == 0:
                cognito.admin_add_user_to_group(UserPoolId=args.pool, Username=username, GroupName="artist")
            result = cognito.initiate_auth(ClientId=args.client, AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={"USERNAME": username, "PASSWORD": password})
            tokens.append(result["AuthenticationResult"]["AccessToken"])

        def create_event(capacity, name):
            code, result = api(args.api, "/events", tokens[0], {
                "name": f"Quantity Test {name} {run_id}", "artist": "Cloud Lab Test", "city": "Barcelona",
                "date": (date.today() + timedelta(days=30)).isoformat(), "price": 25, "capacity": capacity,
            })
            assert code == 201, (code, result)
            return result["eventId"]

        event_id = create_event(100, "100 tickets")
        order_ids, ticket_ids = [], []
        for index, expected in enumerate((96, 92)):
            body = {"eventId": event_id, "quantity": 4, "idempotencyKey": f"{run_id}-buyer-{index}"}
            code, accepted = api(args.api, "/purchases", tokens[index], body)
            assert code == 202, (code, accepted)
            order = settle(args.api, accepted["orderId"], tokens[index])
            assert order["orderStatus"] == "CONFIRMED", order
            assert order["quantity"] == 4 and order["paymentStatus"] == "paid" and len(order["tickets"]) == 4
            assert order["totalPrice"] == 100
            assert len({t["qrPayload"] for t in order["tickets"]}) == 4
            ticket_ids.extend(t["ticketId"] for t in order["tickets"])
            order_ids.append(order["orderId"])
            for ticket in order["tickets"]:
                with urllib.request.urlopen(ticket["qrUrl"], timeout=20) as image:
                    assert image.headers.get_content_type().startswith("image/")
                    assert image.read(8) == b"\x89PNG\r\n\x1a\n"
            status, inventory = api(args.api, f"/events/{event_id}/inventory")
            assert status == 200 and inventory["available"] == expected and inventory["reserved"] == 0
            code, replay = api(args.api, "/purchases", tokens[index], body)
            assert code == 202 and replay["orderId"] == order["orderId"]
            assert api(args.api, "/purchases", tokens[index], {**body, "quantity": 3})[0] == 409
        assert len(set(ticket_ids)) == 8
        assert api(args.api, "/orders/" + order_ids[0], tokens[1])[0] == 404
        assert api(args.api, "/purchases", body={"eventId": event_id, "quantity": 1, "idempotencyKey": "unauth"})[0] == 401
        for q in (0, -1, 1.5):
            assert api(args.api, "/purchases", tokens[0], {"eventId": event_id, "quantity": q, "idempotencyKey": "invalid"})[0] == 400
        report["twoBuyers"] = {"eventId": event_id, "orderIds": order_ids, "distinctTickets": 8, "remainingAfterEach": [96, 92]}

        race_event = create_event(5, "concurrency")
        def buy(index):
            code, result = api(args.api, "/purchases", tokens[index], {
                "eventId": race_event, "quantity": 4, "idempotencyKey": f"{run_id}-race-{index}"})
            if code == 409:
                return {"orderStatus": "INTAKE_REJECTED"}
            assert code == 202, (code, result)
            return settle(args.api, result["orderId"], tokens[index])
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(buy, range(2)))
        assert sum(o["orderStatus"] == "CONFIRMED" for o in outcomes) == 1
        assert all(o["orderStatus"] in ("CONFIRMED", "REJECTED", "INTAKE_REJECTED") for o in outcomes)
        _, inventory = api(args.api, f"/events/{race_event}/inventory")
        assert inventory["sold"] == 4 and inventory["available"] == 1 and inventory["reserved"] == 0
        report["concurrency"] = {"eventId": race_event, "states": [o["orderStatus"] for o in outcomes],
            "orderIds": [o["orderId"] for o in outcomes if "orderId" in o], "sold": 4, "remaining": 1}
        report["result"] = "PASS"
    finally:
        for username in users:
            cognito.admin_disable_user(UserPoolId=args.pool, Username=username)
        report["disabledTestUsers"] = len(users)
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
