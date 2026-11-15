import json
import os

import boto3

cognito = boto3.client("cognito-idp")
POOL_ID = os.environ["USER_POOL_ID"]
GROUPS = ["fan", "artist", "admin"]


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event, context):
    # API Gateway already checked the token. Here we check the ROLE.
    claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    # HTTP API turns the group list into a string such as "[artist admin]".
    groups = str(claims.get("cognito:groups", "")).strip("[]").replace(",", " ").split()
    if "admin" not in groups:
        return _response(403, {"error": "Only admins can change roles"})

    try:
        data = json.loads(event.get("body") or "{}")
    except ValueError:
        return _response(400, {"error": "Body must be valid JSON"})
    if not isinstance(data, dict):
        return _response(400, {"error": "Body must be a JSON object"})

    email = str(data.get("email", "")).strip()
    group = data.get("group")
    if not email or group not in GROUPS:
        return _response(400, {"error": "Send email and group (fan, artist or admin)"})

    try:
        # Add the new group first, then remove the others,
        # so the user is never left without a role.
        cognito.admin_add_user_to_group(UserPoolId=POOL_ID, Username=email, GroupName=group)
        for other in GROUPS:
            if other != group:
                cognito.admin_remove_user_from_group(
                    UserPoolId=POOL_ID, Username=email, GroupName=other
                )
    except cognito.exceptions.UserNotFoundException:
        return _response(404, {"error": "User not found"})

    # The user must log in again to get a token with the new group.
    return _response(200, {"email": email, "group": group})
