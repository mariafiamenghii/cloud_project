# Part B: login, roles and security

Part B owns `infra/cognito.tf`, `infra/api.tf`, `lambdas/post_confirmation/index.py`,
`lambdas/admin_set_role/index.py` and this document. The other parts reuse its
Cognito user pool, web client and JWT authorizer for their own routes.

## Roles

Roles are Cognito groups. The group name travels inside the login token
(`cognito:groups`), so the API and the web can check it without a database.

| Group | Shown in the web as | Can do |
|---|---|---|
| `fan` | student | browse, My Interests, recommendations, buy tickets, My Tickets |
| `artist` | association | everything a fan can, plus publish events, upload images, Sales, delete own events without sales |
| `admin` | admin | everything an association can, for any event, plus change roles |

The names `fan`, `artist` and `admin` are kept on purpose: permissions and stored
data (`artist`, `artistId`) depend on them. Change roles only through the admin
route or the AWS CLI. The user must log out and log in again to get a token with
the new group.

## Sign-up: every new user is a fan

1. In the web, **Log in / Sign up** -> **Create Account** with an email and a
   password (8+ characters with upper case, lower case and a number).
2. Cognito emails a verification code (`auto_verified_attributes = ["email"]`).
   The user types it in the same screen.
3. Cognito then calls the `post_confirmation` Lambda, which adds the user to
   `fan`. If that fails, the sign-up still succeeds and the error is logged in
   CloudWatch; an admin can then set the group.

The code is sent by Cognito's own email service, not SES, so it works in the lab.
That service has a low daily limit (about 50 emails), enough for the demo.
Users created with the AWS CLI do not trigger `post_confirmation`; give them a
group yourself (see below).

## Protected routes

The `cognito` JWT authorizer in `infra/api.tf` checks the token on every private
route before the Lambda runs. A missing or invalid token gets `401` from API
Gateway. It accepts the ID token and the access token of the web client (the web
sends the access token). The Lambda reads the user from the `sub` claim, never
from the request body, and checks the role itself:

| Route | Who |
|---|---|
| `POST /purchases`, `GET /orders`, `GET /orders/{orderId}` | any signed-in user (own orders only) |
| `GET/POST /preferences`, `GET /recommendations` | any signed-in user (own data only) |
| `POST /events`, `POST /event-images/uploads` | `artist` or `admin`, else `403` |
| `GET /my-events`, `DELETE /events/{eventId}` | `artist` (own events) or `admin` (all), else `403` |
| `POST /admin/users/role` | `admin`, else `403` |

`GET /events`, `GET /events/{eventId}/inventory` and `GET /event-images/{eventId}`
are public. Hiding links in the web is only cosmetic; the Lambdas decide.

`POST /admin/users/role` takes `{"email": "...", "group": "fan|artist|admin"}`.
It adds the new group first and then removes the others, so the user is never
left without a role. Unknown user: `404`. Missing email or another group: `400`.

## Demo users (created already verified)

Run in **Bash** (type `bash` first on a Mac), so the hidden prompt works and the
password does not enter shell history. Use the same password rules as above.

```bash
cd infra
POOL=$(terraform output -raw user_pool_id)
read -r -s -p 'Demo password: ' DEMO_PW; echo

create_demo_user() {   # $1 = email, $2 = group
  aws cognito-idp admin-create-user --user-pool-id "$POOL" --username "$1" --message-action SUPPRESS \
    --user-attributes Name=email,Value="$1" Name=email_verified,Value=true
  aws cognito-idp admin-set-user-password --user-pool-id "$POOL" --username "$1" --password "$DEMO_PW" --permanent
  aws cognito-idp admin-add-user-to-group --user-pool-id "$POOL" --username "$1" --group-name "$2"
}
create_demo_user fan@test.com fan
create_demo_user association@test.com artist
create_demo_user admin@test.com admin
```

`--message-action SUPPRESS` sends no email and `email_verified=true` marks the
address as verified, so the users can log in straight away. If a demo user
already exists without verification, run
`aws cognito-idp admin-update-user-attributes --user-pool-id "$POOL" --username association@test.com --user-attributes Name=email_verified,Value=true`.

## Test it

In the same Bash session (after the block above):

```bash
API=$(terraform output -raw api_url)
CLIENT=$(terraform output -raw client_id)
token() {
  aws cognito-idp initiate-auth --auth-flow USER_PASSWORD_AUTH --client-id "$CLIENT" \
    --auth-parameters USERNAME="$1",PASSWORD="$DEMO_PW" --query 'AuthenticationResult.IdToken' --output text
}
FAN=$(token fan@test.com); ASSOC=$(token association@test.com); ADMIN=$(token admin@test.com)

curl -s -o /dev/null -w '%{http_code}\n' $API/my-events                            # 401 (no token)
curl -s -o /dev/null -w '%{http_code}\n' $API/my-events -H "Authorization: Bearer $FAN"    # 403
curl -s -o /dev/null -w '%{http_code}\n' $API/my-events -H "Authorization: Bearer $ASSOC"  # 200

# Only admins can change roles
curl -s -X POST $API/admin/users/role -H "Authorization: Bearer $FAN" -H "Content-Type: application/json" \
  -d '{"email":"fan@test.com","group":"admin"}'                                   # 403
curl -s -X POST $API/admin/users/role -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"email":"fan@test.com","group":"artist"}'                                  # 200
aws cognito-idp admin-list-groups-for-user --user-pool-id "$POOL" --username fan@test.com \
  --query 'Groups[].GroupName'                                                    # ["artist"]
curl -s -X POST $API/admin/users/role -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"email":"fan@test.com","group":"fan"}'                                     # back to fan
unset DEMO_PW
```

New sign-up: create an account in the web with a real email you can read, enter
the code, then check `admin-list-groups-for-user` for that email returns
`["fan"]`. Log in with it: there is no Association Dashboard link, and
`POST /events` with its token returns `403`.

## Known limitations

- No MFA and no social login; email and password only.
- CORS allows any origin (`*`), which is fine for the demo because every private
  route needs a token.
- Changing a role takes effect at the next login (tokens last one hour).
