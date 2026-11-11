# Part C: purchase intake and workflow handoff

Part C owns `infra/purchase.tf`, `lambdas/create_purchase/index.py`,
`lambdas/purchase_worker/index.py`, and `tests/test_purchases.py`.
It uses the existing HTTP API v2, Cognito JWT authorizer, events/orders tables,
SQS queues, and LabRole. On the integration branch, Part D is connected and
hardened; see `docs/INTEGRATION_PURCHASE_WORKFLOW.md` for the combined review.

## HTTP contract

`POST /purchases` requires the same Cognito bearer token used by the existing
authenticated routes. Identity comes from
`requestContext.authorizer.jwt.claims.sub`, never from the request body.

```json
{
  "eventId": "an-existing-event-id",
  "seatId": "1",
  "idempotencyKey": "a-client-generated-uuid"
}
```

- Supply exactly these three fields; `userId`, `orderId`, `forceFail`, payment
  fields, and all other extra fields are rejected.
- `eventId`: nonempty string, no surrounding whitespace, at most 128 characters.
- `seatId`: canonical positive integer string, at most ten digits. `1` as a JSON
  number, `01`, `0`, and `A12` are rejected. The integrated workflow enforces
  the same convention; the frontend must submit it.
- `idempotencyKey`: 1–128 letters, digits, underscores or hyphens. Generate a new
  key for each intentional purchase and keep it for every retry of that purchase.
- Maximum decoded body: 4096 UTF-8 bytes. HTTP API base64 bodies are supported.
- Intake checks that the event exists, capacity is a positive integer, the seat
  is within capacity, and the event is not a Ticketmaster import. These checks
  do not reserve inventory or replace atomic validation in Part D.

Success returns HTTP `202`:

```json
{"orderId": "purchase-<64 hex characters>", "status": "accepted"}
```

This acknowledges enqueueing, or an identical already-dispatched purchase. It
does not promise payment success, a reserved seat, or email delivery. There is no
new order-status endpoint in Part C; inspect DynamoDB/workflow history in tests.

Failures: `400` invalid input/unavailable event or seat, `401` missing identity,
`404` missing event, `409` known key reuse with different purchase details,
`503` database or queue failure. API Gateway rejects invalid JWTs before Lambda.
Retry a `503` or an ambiguous HTTP response using the same key: sending may have
succeeded even when the response was lost.

## Idempotency and persisted orders

The order ID is SHA-256 of an unambiguous JSON pair `[authenticated user, key]`,
prefixed with `purchase-`. It is a valid Step Functions execution name, 73
characters long. Users cannot collide simply by choosing the same client key.
No additional CORS header is needed because the key travels in the JSON body.

Intake reads existing orders consistently. A known conflicting purchase returns
409; an identical dispatched purchase returns 202 without another queue send.
Until the worker has persisted an order, retries may enqueue duplicates. SQS is
unordered: if callers reuse a key for different payloads before persistence,
both requests can return 202. The first **processed** purchase claims the key;
the worker rejects the conflict, retries it, and eventually sends it to the DLQ.
There is no guarantee of synchronous 409 in that race. Never change a purchase
while reusing its key.

The worker accepts exactly `orderId`, `userId`, `eventId`, `seatId`. Queue access
must be restricted to authorized producers/operators; the worker's event is an
SQS event and has no end-user JWT to verify. Direct test sends must use this same
contract. Demo payment-failure flags are not accepted through the public flow.

Before starting execution, the worker conditionally inserts the full order:

| Fields | Purpose |
|---|---|
| `orderId`, `userId`, `eventId`, `seatId` | Immutable purchase identity; supports existing `by-user` GSI |
| `createdAt` | Original creation time in epoch seconds |
| `requestFingerprint` | SHA-256 of canonical workflow input |
| `workflowInput` | Exact canonical JSON string reused on every delivery |
| `workflowArn` | Workflow selected on first persistence, retained across configuration changes |
| `orderStatus = PENDING` | Initial fulfillment status; subsequent status transitions belong to D |
| `dispatchStatus = PENDING` | Handoff not yet durably recorded |

A conditional-write conflict triggers a consistent read and identity comparison.
The worker never replaces an existing order, user association, ticket or status.
Legacy/incomplete orders without this identity metadata require manual review.

After `StartExecution` succeeds, the worker writes only `dispatchStatus = STARTED`
and `executionArn`. STARTED means handoff was accepted, not that fulfillment
succeeded. Duplicate STARTED orders are acknowledged without another execution,
even after Step Functions' 90-day execution-name protection expires. Do not
delete order/idempotency records while requests or redrives may recur.

If execution starts but the response or DynamoDB update is lost, redelivery
reuses the persisted name, input, and ARN. Standard Step Functions returns the
running execution for identical input. For `ExecutionAlreadyExists`, the worker
describes the execution and verifies input and machine identity before recording
the handoff. A matching failed, aborted or timed-out execution is acknowledged,
never restarted as a fresh purchase. D must persist its fulfillment outcome.
Pending orders aged 89 days or more fail closed for manual reconciliation;
they must not silently restart after execution history/name protection expires.

All processing errors return the message ID in `batchItemFailures`. Malformed
or conflicting messages deliberately exhaust the existing five-receive policy
and reach the DLQ. A failed status update is also retried. Review the saved
order and workflow before any DLQ redrive; changing payload/ID is not recovery.

## Integrated Part D workflow

`WORKFLOW_ARN` now references `aws_sfn_state_machine.purchase.arn` directly in
`infra/purchase.tf`. The state machine is STANDARD and lives in this same root
module. Terraform therefore creates an explicit dependency; the standalone
`purchase_workflow_arn` variable has been removed on this integration branch.
Remove any obsolete local value for that variable before a later deployment.
No credential or Terraform state changes are needed.

The four-field JSON contract remains unchanged. Reservation and payment task
results remain nested under `reserve` and `payment`; ticket generation adds
its stable ticket fields at the top level for notification.

The integrated implementation now provides:

1. Atomic event-capacity check, conditional seat reservation and order status.
2. Same-order reservation retries and reclamation of expired held seats only.
3. Durable simulated payment, conditional on ownership of a valid hold.
4. Atomic sold-seat confirmation and ticket issuance on the existing paid order.
5. Ownership-safe unpaid compensation that also records failure atomically.
6. Persistent CONFIRMED, REJECTED, FAILED and REVIEW_REQUIRED outcomes without
   replacing C's identity, idempotency or dispatch metadata.
7. Bounded infrastructure retries, separate post-payment review and best-effort
   SES notification. Failed email does not free inventory or fail the purchase.

An SQS message is deleted after handoff. Subsequent workflow failures do not
return to SQS or its DLQ. For uncertain paid fulfillment, inspect the existing
order and execution: do not change the purchase ID and start a new purchase.
The full recovery limits and AWS test requirements are in the integration doc.

## Academy IAM requirements

LabRole is reused without changing shared role policies or trust. Verify its
effective permissions in the lab before deployment:

- Producer: `dynamodb:GetItem` on events/orders, `sqs:SendMessage` on this queue,
  and CloudWatch Logs writes.
- Worker: `dynamodb:PutItem`, `GetItem`, `UpdateItem` on orders;
  `states:StartExecution` on the configured state machine;
  `states:DescribeExecution` on its executions; existing SQS receive/delete/get
  attributes and CloudWatch Logs permissions.
- D: workflow Lambda invocation; DynamoDB GetItem/UpdateItem plus the PutItem,
  UpdateItem and ConditionCheckItem permissions used by transactional actions
  on events/seats/orders; SES SendEmail; and CloudWatch Logs. LabRole must trust
  `states.amazonaws.com` in addition to Lambda. These effective permissions
  remain unverified until the authorized Academy checks.
- Terraform's execution identity needs the existing deployment permissions,
  including passing LabRole. Part C does not create or broaden IAM roles.

## Local checks

Python 3.12 is the Lambda runtime. Tests use Python's standard-library unittest
and boto3/botocore, which are supplied by Lambda and must also be available in
the local development environment. Integrated tests additionally use the
Moto emulator from `tests/requirements.txt`; it is not packaged into Lambda.

Install `tests/requirements.txt` in a local virtual environment. From the repository root:

```bash
python3 -B -m unittest discover -s tests -v
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate -no-color
git diff --check
```

Terraform validation requires previously initialized local providers. It does
not deploy resources. C tests replace SDK clients/resources before invocation. Integrated tests use
Moto in memory, dummy credentials and an isolated environment; neither suite
contacts real AWS. Workflow graph checks evaluate HCL in a temporary directory
without providers or a backend. They cover intake,
base64/invalid bodies, event capacity, identity spoofing, duplicate/conflicting
requests, conditional order creation, concurrent deliveries, transient errors,
lost handoff updates, closed-execution reconciliation, partial failures, and
old pending-order protection. Mocked conditions do not prove AWS concurrency.

## AWS Academy tests (separate approval required)

No deployment or AWS tests have been run for this change. After the team
authorizes deployment:

1. Review the Terraform plan, STANDARD workflow ARN, LabRole permissions/trust,
   and SES identity in the chosen region.
2. Use one tiny event with capacity two and an authenticated test user.
3. Verify missing/invalid JWT rejection and a valid POST returning 202.
4. Repeat the same key before/after processing: one full order and execution;
   another user's identical key must identify a different order.
5. Verify known key/payload conflicts return 409 and queued conflict races do
   not overwrite the first persisted purchase.
6. Check invalid capacity/seat/event rejection, including Ticketmaster imports.
7. Check same-seat concurrency, hold expiry, permanent sold-seat protection and
   ownership-safe compensation in real DynamoDB.
8. Exercise transient start errors, DLQ behavior and handoff reconciliation
   using a few controlled messages; do not load test initially.
9. Inspect post-payment ticket/email failure statuses separately from the SQS
   DLQ. Confirm all order identity and dispatch metadata survives D's updates.

Deployment and eventual cleanup remain separate authorized actions. Keep
fixtures and message counts tiny to minimize Academy costs.
