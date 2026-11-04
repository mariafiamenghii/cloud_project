# Ticketing platform (Terraform starter)

First working slice: **list events (public)** and **create events (artists only)**,
with login and roles through Cognito. Everything else is added file by file.

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

# 2) create a test artist
aws cognito-idp admin-create-user --user-pool-id $POOL --username artist@test.com --message-action SUPPRESS
aws cognito-idp admin-set-user-password --user-pool-id $POOL --username artist@test.com --password 'Test1234' --permanent
aws cognito-idp admin-add-user-to-group --user-pool-id $POOL --username artist@test.com --group-name artist

# 3) log in and copy the IdToken from the output
aws cognito-idp initiate-auth --auth-flow USER_PASSWORD_AUTH --client-id $CLIENT \
  --auth-parameters USERNAME=artist@test.com,PASSWORD=Test1234

# 4) create an event with that token
curl -X POST $API/events -H "Authorization: Bearer <IdToken>" -H "Content-Type: application/json" \
  -d '{"name":"Test concert","city":"Barcelona","date":"2026-12-20","price":25,"capacity":100}'
```
Without a token the POST returns 401. With a fan token it returns 403.

## Rules
- Never commit `terraform.tfstate`, `terraform.tfvars`, `.env` or AWS keys (see `.gitignore`).
- Run `terraform fmt` before every commit (CI checks it).
- Seats: reserve with a conditional write that also accepts expired holds.
  Do not rely on DynamoDB TTL to free seats (deletion can be delayed).
