# Purchase workflow integration review

## Git sources and scope

The integration starts from Part C `69f41a1` on
`feature/integration-purchase-workflow`. Origin was fetched before integration.
`origin/feature/workflow-ticket-email` still points to the original `45a3015`.
Its later fixes are `f94b1ba` (best-effort email) and `5a2437a` (seat state),
already merged into `origin/main` at `762e95d`.

The integration merges `origin/fix/seat-state-no-oversell` with `--no-commit
--no-ff`. That history includes D and both fixes, and its tree matches the fetched
origin/main. No main or teammate branch is changed. Additional correctness fixes
exist only on the integration branch. The merge is intentionally not committed;
there must be explicit user approval before committing, pushing or deploying.

Only purchase/workflow code, packaging, tests and documentation are changed.
Existing A/B/E APIs, Cognito configuration, table keys/indices, import scripts,
queue/DLQ settings and worker concurrency/timeouts are preserved. No new AWS
service or additional Lambda function is introduced beyond D's original five.

## What the fetched D fixes did and what remained

| Area | Fetched fixes | Integration correction |
|---|---|---|
| Capacity | Preliminary read; optional if environment missing | Required table, strict positive integral capacity, canonical seat IDs, event check in reservation transaction |
| Seat IDs | `int()` accepted aliases such as `01` and `+1` | Same canonical `1..capacity` contract as C |
| Reservation | Conditional seat write, with same-order retry | Event check + owned hold + existing order transition in one transaction |
| Confirmation | Marked seat sold before separate order write | Sold seat and stable ticket/order written atomically |
| Compensation | Only released this order's held seat | Retains ownership checks; atomically terminalizes an unpaid order and releases its hold |
| Payment | New random simulated payment on each invocation | Persisted payment with deterministic ID and original timestamp; conditional valid hold |
| Fulfillment failures | No durable outcomes beyond ticket fields | Separate unpaid failure and paid review; no release after known payment |
| Notification | Best-effort SES result in execution output | Same intended behavior, with durable email outcome and known-sent replay suppression |

## Contract and state transitions

The authenticated HTTP contract and worker validation remain in `PART_C.md`.
The workflow starts with exactly `orderId`, `userId`, `eventId`, `seatId`.
The worker persists the order before starting a STANDARD execution. Every D task
checks that its user/event/seat match that existing order; D cannot manufacture
an incomplete order or overwrite a different user's purchase.

Normal order states are `PENDING -> RESERVED -> PAID -> CONFIRMED`.
`paymentStatus = paid` and payment ID/time are persisted at PAID.
`ticketStatus = issued` and stable QR fields are persisted at CONFIRMED.
Ticket timestamp uses the persisted payment time so retries keep the same QR.
Confirmation and the seat's transition from held to sold are one transaction.
Sold seats have no expiry and cannot be re-reserved. C's request fingerprint,
saved execution input/ARN, user index key and dispatch fields survive all updates.

An unpaid business reservation rejection records REJECTED. Other pre-payment
failures record FAILED. Failure recording and release are one transaction:
payment and compensation racing each other cannot both succeed. A late release
cannot free a newer owner's seat or a sold seat. Matching already-terminal
failure records are safe to process again.

Known paid failures record REVIEW_REQUIRED without releasing inventory.
Notification failures preserve CONFIRMED and record `emailStatus = not_sent`.
The existing release Lambda handles these failure stages without adding another
function. Reservation/payment results remain nested at `$.reserve`/`$.payment`;
ticket fields become top-level, and email output is stored at `$.email`.

The worker now references `aws_sfn_state_machine.purchase.arn` directly. The
standalone external ARN variable is removed; an old local setting should be
removed before deployment. The STANDARD type, direct Lambda invocation format,
task result paths and four identifiers agree with C. Each of D's five ZIPs
includes `index.py` and the shared `purchase_common.py`; the archive hash includes
both. No Moto, tests or development dependencies are included in those ZIPs.

## Explicit limits and recovery policy

- Payment remains a simulation, with no external charge or refund API. This
  integration does not invent a refund policy or switch to real payments.
- The workflow has a five-minute bound within the existing fifteen-minute hold.
  If a paid order stalls beyond its hold, it cannot confirm an expired/lost
  seat. If another order has reclaimed the expired hold, the original gets no
  ticket and requires manual review; it cannot sell the newer owner's seat.
  REVIEW_REQUIRED is a deliberate stop, not an automatic retry/refund.
- Capacity is checked atomically when holding inventory. There is no capacity
  editor in the current API. Do not reduce an event's capacity or overwrite a
  selling event through imports/admin writes while sales exist; safe dynamic
  capacity management would be a separate design change.
- Standard execution names plus persistent orders provide purchase idempotency.
  Do not delete order records, change immutable fields or replay under new IDs
  to recover a failed purchase. Review/terminal statuses intentionally prevent
  automatically reviving an old order. Use tiny fresh fixtures in lab tests.
- SES still sends FROM and TO the same configured verified demo address.
  Already-recorded sent notifications are skipped. SES has no idempotency token:
  a lost response, a failed status write or concurrent notification invocation
  can cause a repeated email. It cannot cause another payment or ticket.
- Bounded retries target infrastructure errors, not SeatUnavailable,
  PaymentFailed or SeatLost. If failure recording also cannot access DynamoDB,
  or an execution is aborted/times out globally, no catch can guarantee a final
  database status. Inspect execution history and the saved order. An unconfirmed
  unpaid hold expires; paid outcomes require review before any intervention.
- No background reconciliation, refund service, new order API, external payment
  provider, purchaser-recipient change or capacity-edit API is introduced.

## IAM and deployment prerequisites (not checked against AWS)

The reused LabRole and trust policies are external to Terraform. Existing
SQS/Lambda success does not prove the integrated permissions work. Before a
separately approved deployment, verify:

- Lambda and Step Functions can assume LabRole. The state machine can invoke its
  five functions; each function can write CloudWatch Logs.
- C's producer has event/order GetItem and queue SendMessage; its worker has
  order PutItem/GetItem/UpdateItem, queue receive/delete/get attributes,
  StartExecution on this state machine and DescribeExecution on its executions.
- Workflow functions have GetItem and UpdateItem on the relevant tables. Their
  transactions require the corresponding UpdateItem and ConditionCheckItem
  permissions on events/seats/orders. Do not assume the transaction API name
  alone is an IAM permission grant. Verify scoped policies with the lab owner;
  this integration does not broaden the shared role.
- SES SendEmail is allowed, `notify_email` is nonempty, and that identity has
  been verified in the same region. Terraform's email-identity declaration
  cannot complete the human verification link itself.

AWS documents the all-or-nothing behavior of these operations in its
[transaction API reference](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_TransactWriteItems.html)
and the underlying action permissions in
[Using IAM with DynamoDB transactions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis-iam.html).

## Local verification

Use Python 3.12, Terraform and an isolated Python environment:

```bash
python -m pip install -r tests/requirements.txt
python -B -m unittest discover -s tests -v
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate -no-color
git diff --check
git diff --cached --check
```

C's original 24 tests remain intact. Integrated tests exercise the HTTP intake,
emulated SQS message, real SDK DynamoDB requests, transaction rollbacks,
canonical inventory limits, ownership, duplicate/lost responses, payment versus
compensation races, expired holds and best-effort notifications. Workflow graph
tests evaluate the actual Terraform definition with placeholder function ARNs
in a provider-free temporary configuration and check catch/retry contracts.
Moto runs in memory with dummy credentials: no test contacts Academy. These
checks validate local behavior, not real IAM, AWS contention or SES delivery.

## Later AWS Academy validation

No deployment, Terraform plan/apply/destroy or real resource creation was run.
After approval, review a plan and verify the IAM/SES prerequisites. Deploy one
tiny event of capacity two and send only a few purchases. Verify JWT enforcement,
repeated API submissions and SQS deliveries, two buyers competing for one seat,
out-of-capacity rejection, paid-seat permanence after hold expiry, and durable
order/ticket fields. Exercise controlled payment failure, expired-hold review,
post-payment ticket errors, blocked SES, and SQS retry/DLQ behavior separately.
Verify real transaction contention and failure-recording permissions, including
DescribeExecution for closed duplicate starts. Cleanup is a separate authorized
action; do not load test until the small correctness tests pass.
