# FRONT ROW: events for the ESADE community and Barcelona

A serverless event-ticketing platform on AWS, deployed with Terraform.

- **ESADE student associations** (Consulting, Finance, Tech, Luxury...) publish
  their events and sell tickets in the app (SQS + Step Functions purchase flow,
  no overselling, QR tickets).
- **Barcelona city events** are imported from the City Council open data agenda
  (`scripts/import_bcn_agenda.py`). They are only shown, with a link to the
  official page. Ticketmaster imports are legacy and being removed.
- **Students** browse and filter events, answer an interests survey (topics and
  associations they follow) and get personal recommendations.

Every event has one category from a shared list: `CATEGORIES` in
`web/src/utils/eventMedia.ts`, with a backend copy in
`lambdas/create_event/categories.py` (a test keeps both identical). It is
stored lowercase in the event's `genre` field.

Roles are Cognito groups. In the web, the `artist` group is called
**association**; the group names `fan`, `artist` and `admin` stay as they are
because permissions depend on them.

## Folders
- `infra/`   Terraform code (all AWS resources)
- `lambdas/` One folder per Lambda function (code)
- `web/`     The website (added later)

## Who edits which file (to avoid merge conflicts)
| Person | Area | Terraform files |
|---|---|---|
| A | Website + hosting | `frontend.tf` (new) |
| B | Login, roles, security | `cognito.tf`, `api.tf` |
| C | Purchase flow (SQS, worker, seats) | `purchase.tf` (new) |
| D | Workflow, ticket, email | `workflow.tf` (new) |
| E | Data, survey, recommendations, import, load test | `dynamodb.tf`, `recommendations.tf` (new) |

Add a new Lambda by copying the pattern in `infra/events_api.tf`
(archive_file -> aws_lambda_function -> integration -> route -> permission).

## Deploy to your own AWS Academy account
1. Start the lab and save the credentials in `~/.aws/credentials` (they expire every session).
2. Check: `aws sts get-caller-identity`
3. Then:
```
cd infra
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform plan
terraform apply
```
4. Remove everything when you stop working: `terraform destroy`

If `apply` fails with a permission error, send the exact message to the teacher.
Check early that Cognito, API Gateway and Lambda are allowed in your lab.

## Test it (no website needed)
```
cd infra
API=$(terraform output -raw api_url)
POOL=$(terraform output -raw user_pool_id)
CLIENT=$(terraform output -raw client_id)

# 1) public list (empty at first)
curl $API/events

# 2) create a test association (Cognito group "artist")
aws cognito-idp admin-create-user --user-pool-id $POOL --username association@test.com --message-action SUPPRESS \
  --user-attributes Name=email,Value=association@test.com Name=email_verified,Value=true
aws cognito-idp admin-set-user-password --user-pool-id $POOL --username association@test.com --password 'Test1234' --permanent
aws cognito-idp admin-add-user-to-group --user-pool-id $POOL --username association@test.com --group-name artist

# 3) log in and copy the IdToken from the output
aws cognito-idp initiate-auth --auth-flow USER_PASSWORD_AUTH --client-id $CLIENT \
  --auth-parameters USERNAME=association@test.com,PASSWORD=Test1234

# 4) create an event with that token ("artist" = association name, "genre" = category)
curl -X POST $API/events -H "Authorization: Bearer <IdToken>" -H "Content-Type: application/json" \
  -d '{"name":"Finance Club Networking Night","artist":"ESADE Finance Club","genre":"networking","city":"Barcelona","date":"2026-12-20","price":10,"capacity":100}'
```
Without a token the POST returns 401. With a fan token it returns 403. A
`genre` outside the category list returns 400.

## Rules
- Never commit `terraform.tfstate`, `terraform.tfvars`, `.env` or AWS keys (see `.gitignore`).
- Run `terraform fmt` before every commit (CI checks it).
- Tickets are general admission: change an event's `sold`/`reserved`/`available`
  counters only inside the same transaction as the order change
  (see `docs/QUANTITY_PURCHASES.md`). Do not rely on DynamoDB TTL to free
  reserved tickets (deletion can be delayed).
- Keep the category lists in `web/src/utils/eventMedia.ts` and
  `lambdas/create_event/categories.py` identical (`tests/test_categories.py`).

## More docs
- Part A (frontend feedback, Amplify deployment and GitHub token): see `docs/PART_A.md`
- Part B (login, roles, protected routes, demo users): see `docs/PART_B.md`
- Part C (purchase API and worker): see `docs/PART_C.md`
- Part D (purchase workflow, QR ticket, email): see `docs/PART_D.md`
- Part E (sample data, Barcelona import, interests survey, recommendations, load test): see `docs/PART_E.md`
- Event images: `docs/EVENT_MEDIA.md`. Ticket quantities: `docs/QUANTITY_PURCHASES.md`
