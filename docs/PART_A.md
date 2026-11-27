# Part A: frontend and Amplify

## Feedback status

- The Association Dashboard and Sales pages are restricted to authenticated
  Cognito `artist` (shown as "association" in the web) and `admin` users,
  matching backend publishing permissions. Public/demo visitors and fans do not
  get the links. The pages also check permissions. Log out and log back in after
  changing a Cognito group so the tokens contain the new group.
- Welcome uses the user's name or email, falling back to `User`, never the UUID.
- Selected interests and followed associations in the My Interests survey have
  a checkmark, purple background, outline and `aria-pressed` state.
- The event form's category list is the shared `CATEGORIES` list, and the
  category is required.
- Discover and Recommended for You hide past events and sort by ascending date.
  Date-only events remain visible throughout their day in Europe/Madrid;
  timestamps are compared with the current instant. Invalid dates are hidden.
- Recommendations pass available capacity and the purchase handler to event cards.
- Purchase intake currently returns `202 {orderId, status: "accepted"}`. The UI
  correctly labels this as accepted for processing, not a confirmed ticket.

## Why tickets can be unavailable

`EventCard` needs positive `capacity` for an in-app purchase. Records with missing
or zero capacity cannot be booked. The UI explains the reason under the button.
`data/sample_events.json` contains ESADE association events with positive capacity,
so records loaded with `scripts/load_events.py` can be bought from Discover Events.
Older records without capacity need to be reloaded or corrected by the data owner.
The local recommendation examples have no inventory and are labelled samples.

Barcelona city events (`source: "barcelona_open_data"`) and legacy Ticketmaster
imports deliberately have `capacity: 0`: we do not sell those tickets. Their
`externalUrl` opens the official page ("More info"). If that URL is missing, the
card explains that no booking link is available.

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
   Welcome, a fan account without the Association Dashboard, and an association
   account with it. Select/deselect interests in My Interests and verify their
   visual state. Confirm events are future events in date order. Buy a ticket for
   an ESADE association event: it should show an order reference, then the QR
   ticket once confirmed. Verify the "More info" links of Barcelona events separately.

If the Academy role denies Amplify actions, send the exact denied action to the
teacher/lab owner. A successful local build does not mean hosting was deployed.

## Purchase outcome (C and D)

Implemented. `GET /orders/{orderId}` (`infra/workflow.tf`, Part D) returns the
caller's own order with its status and QR ticket; another user's order returns
404. `GET /orders` (`infra/my_tickets.tf`) lists the caller's orders for My
Tickets. The Purchase page polls the order with bounded retries, treats a
temporary 404 as "still being processed" while the queued worker creates the
order, and stops when leaving the page. It shows the ticket only for
`CONFIRMED`, explains `REJECTED`/`FAILED`, and shows a review message for
`REVIEW_REQUIRED`. A network error or polling timeout keeps the reference and a
pending outcome, rather than claiming the purchase failed or charging again.

## Local validation

From `web/`, run `npm run build` and `npm run lint`. Date filtering regression
checks can be run with Node 22.18+ using `npm test`.
