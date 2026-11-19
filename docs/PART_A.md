# Part A: frontend and Amplify

## Feedback status

- Artist Dashboard is restricted to authenticated Cognito `artist` and `admin`
  users, matching backend publishing permissions. Public/demo visitors and fans
  do not get the button. The page also checks permissions. Log out and log back
  in after changing a Cognito group so the tokens contain the new group.
- Welcome uses the user's name or email, falling back to `User`, never the UUID.
- Selected survey genres have a checkmark, purple background, outline and
  `aria-pressed` state.
- Discover and Recommended for You hide past events and sort by ascending date.
  Date-only events remain visible throughout their day in Europe/Madrid;
  timestamps are compared with the current instant. Invalid dates are hidden.
- Recommendations pass available capacity and the purchase handler to event cards.
- Purchase intake currently returns `202 {orderId, status: "accepted"}`. The UI
  correctly labels this as accepted for processing, not a confirmed ticket.

## Why tickets can be unavailable

`EventCard` needs positive `capacity` for an in-app purchase. Records with missing
or zero capacity cannot be booked. The UI explains the reason under the button.
`data/sample_events.json` currently contains positive capacity, so records loaded
with `scripts/load_events.py` should allow purchase from Discover Events. Older
records without capacity need to be reloaded or corrected by the data owner.
The local recommendation examples have no inventory and are labelled samples.

Ticketmaster imports deliberately have `capacity: 0` and `source: "ticketmaster"`:
we do not sell those tickets. Their `externalUrl` opens the official seller.
If that URL is missing, the card explains that no booking link is available.

## Deploy the real Amplify app

The Terraform app follows `main` in
`https://github.com/mariafiamenghii/cloud_project` and builds `web/` with `npm ci`
and `npm run build`. Merge the reviewed frontend changes there before deploying
them. AWS values are injected by Terraform; `VITE_DEMO_MODE` is explicitly false.
No AWS credentials or GitHub token belong in any `VITE_*` variable: those values
are included in browser code.

1. Start the AWS Academy lab and configure its current temporary credentials
   locally, including the session token. Use the team's existing Terraform state;
   do not create another copy of resources already managed by Terraform.
2. The repository owner must install the regional Amplify GitHub App for this
   repository. For the default region, use
   <https://github.com/apps/aws-amplify-us-east-1>. Follow the AWS access guide to
   create a PAT with the permissions required for that connection:
   <https://docs.aws.amazon.com/amplify/latest/userguide/setting-up-GitHub-access.html>.
3. Supply the PAT via a hidden shell prompt. Run this in **Bash**, so the token
   itself does not enter shell history. Do not paste it in chat or a committed file.

   ```bash
   cd infra
   read -r -s -p 'GitHub token: ' TF_VAR_github_access_token
   echo
   export TF_VAR_github_access_token
   aws sts get-caller-identity
   terraform init
   terraform fmt -check -recursive
   terraform validate
   terraform plan
   ```

4. Review the plan for the whole stack. When ready, apply it and clear the shell
   variable (Terraform will ask for the normal plan confirmation).

   ```bash
   terraform apply
   unset TF_VAR_github_access_token
   ```

   `sensitive = true` hides the value in normal Terraform output; it does not
   encrypt Terraform state or saved plans. Keep those private and outside Git.
   See <https://developer.hashicorp.com/terraform/language/manage-sensitive-data>.
   Future Terraform runs may need the input again; repeat the hidden prompt.

5. Creation of an Amplify app and branch is not evidence of a successful build.
   Check the Amplify console for an active or successful job. If there is none,
   start the initial release and inspect its job ID:

   ```bash
   APP_ID=$(terraform output -raw frontend_app_id)
   BRANCH=$(terraform output -raw frontend_branch)
   REGION=$(terraform output -raw region)
   aws amplify start-job --app-id "$APP_ID" --branch-name "$BRANCH" --job-type RELEASE --region "$REGION"
   aws amplify list-jobs --app-id "$APP_ID" --branch-name "$BRANCH" --max-results 5 --region "$REGION"
   # Replace JOB_ID with the jobId returned above.
   aws amplify get-job --app-id "$APP_ID" --branch-name "$BRANCH" --job-id JOB_ID --region "$REGION"
   terraform output -raw frontend_url
   ```

6. Wait for `SUCCEED`, then open the URL. Verify public events, email login,
   Welcome, a fan account without Artist Dashboard, and an approved artist account
   with it. Select/deselect survey genres and verify their visual state. Confirm
   events are future events in date order. Try an internal test concert purchase:
   it should show an order reference and accepted-for-processing state. Verify
   Ticketmaster links separately.

If the Academy role denies Amplify actions, send the exact denied action to the
teacher/lab owner. A successful local build does not mean hosting was deployed.

## Pending dependency: purchase outcome (C)

There is currently no order-status GET route in `infra/purchase.tf`. Agree the
actual endpoint and response with C before adding frontend polling. Proposed
contract, **not implemented**:

```text
GET /purchases/{orderId}   Authorization: Bearer <Cognito token>
200 {"orderId": "...", "orderStatus": "CONFIRMED"}
```

The handler must check the authenticated user owns the order. Agree how to
handle a temporary 404 while the queued worker creates the order. Existing
workflow states are `PENDING`, `RESERVED`, `PAID`, `CONFIRMED`, `REJECTED`, `FAILED`
and `REVIEW_REQUIRED`. Once the endpoint exists, poll with bounded retries and
cancel when leaving the page; display confirmed only for `CONFIRMED`, explain
`REJECTED`/`FAILED`, and show a review message for `REVIEW_REQUIRED`. A network
error or polling timeout must preserve the reference and an unknown/pending
outcome, rather than claiming the purchase failed or charging again.

## Local validation

From `web/`, run `npm run build` and `npm run lint`. Date filtering regression
checks can be run with Node 22.18+ using `npm test`.
