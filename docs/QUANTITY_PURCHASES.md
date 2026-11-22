# General admission purchases

## Contracts

`POST /purchases` requires a Cognito access token and exactly:

```json
{"eventId":"event-id","quantity":4,"idempotencyKey":"request-key"}
```

Quantity must be an integer from 1 to 20. The API returns 202 with a stable
`orderId` and `status=accepted`. This acknowledges dispatch, not ticket issuance.
The key is scoped to the authenticated buyer; changing parameters under the
same key returns 409. Retries after SQS errors reuse the persisted order.
The worker starts one deterministic Standard Step Functions execution.

`GET /orders/{orderId}` remains protected and owner-scoped. A confirmed v2 order
includes `schemaVersion=2`, `quantity`, `unitPrice`, `totalPrice`, and `tickets`:

```json
{
  "orderId":"purchase-...",
  "schemaVersion":2,
  "eventId":"event-id",
  "quantity":4,
  "unitPrice":25,
  "totalPrice":100,
  "orderStatus":"CONFIRMED",
  "paymentStatus":"paid",
  "ticketStatus":"issued",
  "tickets":[
    {"ticketId":"ticket-...","ticketNumber":1,"qrPayload":"TICKET|...","qrUrl":"https://api.qrserver.com/..."}
  ]
}
```

The illustration abbreviates the array; a real four-ticket confirmation contains
exactly four ticket records. Other users receive the same 404 as a missing order.
Historical order responses preserve their original single-ticket QR fields.

`GET /events/{eventId}/inventory` publicly returns a strongly consistent snapshot
of capacity, sold, reserved, available, price, inventoryVersion and the per-order
limit. It supports internal events only. GET /events also includes these counters.
The purchase page refreshes inventory every ten seconds. The backend transaction
always decides whether inventory is still available.

## Data and transitions

Existing event records gain `inventoryVersion=2`, `sold`, `reserved`, `available`.
The invariant is `capacity = sold + reserved + available`, with no negative counter.
New artist-created events initialize these fields. Event IDs remain unchanged.

One additive table, `ticketing-tickets`, has partition key `orderId` and sort key
`ticketId`. Each row describes exactly one issued ticket. Ticket IDs are derived
from order ID and unit index, and QR payloads identify that ticket. Strongly
consistent queries on the base table return the full set after confirmation.
There is no GSI consistency delay. The table has Terraform `prevent_destroy`.

The existing Step Functions state machine and Lambda names are retained. The
ReserveSeat state dispatches v2 requests to general admission reservation logic;
legacy names do not represent seat selection in the v2 contract.

1. A transaction subtracts quantity from available and adds it to reserved,
   conditional on enough available tickets, while moving the matching order
   PENDING → RESERVED/HELD. It snapshots unit and total price.
2. Simulated payment conditionally changes the same order to PAID while its
   reservation is still valid. Payment never repeats for a paid order.
3. One transaction creates all N immutable ticket rows, moves N reserved to sold,
   and changes the order to CONFIRMED/issued/SOLD. It commits all or nothing.
4. Notification records `not_sent`; SES is unavailable in the lab.

All counter changes are guarded by an order transition in the same transaction.
Replayed reservations or issuance cannot deduct inventory twice. Independent
requests for four tickets do not contend on a seat ID; only available capacity
limits them. The 20-ticket limit keeps transactions and status responses bounded.

Payment failure releases only an unpaid HELD reservation and marks it RELEASED
in the same transaction. A concurrent payment or confirmation prevents that
release. A failure after payment retains all reserved inventory and records
REVIEW_REQUIRED. An operator may reconcile the original persisted v2 input through
the issuance function: it produces the same logical ticket set, atomically, or
does nothing if already issued. Never generate a new order/execution identity for
paid recovery.

The normal workflow compensates expired unpaid holds. A workflow-level timeout
or interrupted lab can leave reserved inventory conservatively held. Do not use
DynamoDB TTL or a blind counter reset to reclaim it. Reconcile the execution and
the guarded order transition first; an unknown paid outcome must retain inventory.

## Legacy compatibility and migration

Legacy `seatId="4"` always means one historical numbered-seat ticket. It never
becomes quantity four. Legacy messages retain their exact serialized workflow
input and fingerprint. Legacy handlers remain for draining pre-upgrade work.
Once an event is migrated, new seat-based requests are rejected with an explicit
refresh/quantity-contract message; retries of already dispatched legacy orders
still return their original identity. Legacy reservation transactions are fenced
off from migrated events.

`scripts/migrate_quantity_inventory.py` is read-only without `--apply`. It scans
all pages with strong consistency and skips Ticketmaster events and already
migrated events. For each legacy event it validates every confirmed paid/issued
order against its sold seat and counts one unit per historical order. It refuses
unresolved orders, any held seat, missing/orphan sold seats, invalid capacity,
or historical sales over capacity. It never modifies orders, seats or old QR codes.
Conditional event updates add only counters, legacySold and a migration digest.
Reruns skip migrated records and cannot count historical sales twice.

Deployment sequence, requiring explicit approval:

1. Inspect queues, DLQ, running executions and a dry-run migration report.
2. Review `terraform plan -var=purchases_enabled=false`. Apply only the approved
   plan. This temporarily sets reserved concurrency to zero for purchase intake
   and event creation, and disables intake through its environment flag. Existing
   legacy worker processing can drain through the compatible handlers.
3. Recheck quiet queues/executions and freeze; snapshot historical data, then run
   the migration with `--apply`. The script independently enforces these guards.
4. Verify migrated counters and unchanged historical records. Review/apply a plan
   with `purchases_enabled=true` to reopen intake and event creation.
5. Merge the tested frontend PR into main and verify Amplify's matching commit.
   Old browser tabs receive a refresh message for a new seat-based request.

Do not roll back to a seat-only backend after migrating events. Keep v2 inventory
guards active and pause intake if a rollout needs repair. Never destroy existing
tables or the Amplify app. Plans/state contain secrets and must remain local.

## Validation

The test suite covers quantities one/four, two buyers reaching 96 then 92 remaining,
competing preaccepted orders, invalid quantities, auth and ownership, idempotency,
lost issuance responses, safe payment compensation, QR failure and paid recovery,
legacy QR preservation, versioned worker dispatch, and historical reconciliation.
Moto transaction calls in the threaded test are serialized because Moto does not
provide DynamoDB's production transaction isolation; live AWS checks are also
required before claiming deployed concurrency behavior.

Frontend tests check integer input and complete/unique ticket rendering, including
historical tickets. ESLint, TypeScript/Vite, Python tests and Terraform validation
are part of release verification. Vite's existing bundle-size warning remains.
Payment and email are simulated; QR images depend on api.qrserver.com. The UI has
no My Tickets page; the current purchase confirmation shows every order ticket.

## Deployed AWS evidence — 22 November 2026

Approved initial Terraform apply: 2 additions (ticket table, inventory route),
10 Lambda updates, 0 deletions. Approved reopening apply: 2 in-place updates,
0 additions/deletions. The existing Amplify app, queues, state machine and
stateful tables were retained.

Migration verified all 22 old orders, 10 seat records and 272 Ticketmaster event
records unchanged. Ten internal events were migrated with ten historical sales
included exactly once. The live API test uses two isolated Cognito accounts
(one artist) with generated credentials held only in memory; both accounts were
disabled afterwards. Test events and orders remain available for audit.

Authenticated API test (`scripts/test_quantity_live.py`):

- Event `f2cc801f-710f-4a1d-bff9-1580f02e9519`, capacity 100, unit price EUR 25.
- Buyer A: `purchase-e9cfe8560cb3fe5b82d55d9eac051084fc49d50c6d3ed3a1bdc8e33ed58a6a31`.
- Buyer B: `purchase-db7376583d8c80ae86fe14a5178330e1a63dfcb18c24a9c0defee2a897b89a46`.
- Each order CONFIRMED four tickets and EUR 100 total; eight ticket IDs and QR
  payloads were distinct. All eight QR URLs returned PNG images. Remaining
  availability was 96 after A and 92 after B.
- Same-key retries returned the same order, changed quantities returned 409,
  invalid quantities returned 400, unauthenticated purchase returned 401, and
  buyer B reading A's order returned 404.
- An API concurrency event `b03c17f3-db73-4ce4-8c6c-c6d552f268d5` with capacity 5
  accepted one four-ticket purchase and rejected the other at intake; 1 remained.

A second live concurrency test bypassed intake timing by persisting both test
orders before invoking the actual deployed reservation Lambdas concurrently.
Event `quantity-atomic-3777f81ee6fb` had capacity 5. Orders ending `-0` and `-1`
requested four units each: one became CONFIRMED and the other REJECTED. Final
counters: sold 4, reserved 0, available 1. This tests actual DynamoDB conditional
transactions, independently of Moto's limitations. These isolated direct-call
fixtures have `dispatchStatus=DIRECT_TEST` and do not claim a Step Functions run.

Local verification: 64 Python tests, nine frontend tests, ESLint, TypeScript/Vite,
Terraform validate/fmt and diff whitespace checks passed.

## Changed files

- Infrastructure: `infra/dynamodb.tf`, `infra/events_api.tf`, `infra/purchase.tf`,
  `infra/variables.tf`, `infra/workflow.tf`.
- Lambdas: `lambdas/create_event/index.py`, `lambdas/create_purchase/index.py`,
  `lambdas/generate_ticket/index.py`, `lambdas/get_order/index.py`,
  `lambdas/list_events/index.py`, `lambdas/purchase_worker/index.py`,
  `lambdas/release_seat/index.py`, `lambdas/reserve_seat/index.py`,
  `lambdas/send_email/index.py`, `lambdas/take_payment/index.py`,
  `lambdas/workflow_common/quantity_workflow.py`.
- Frontend: `web/src/components/EventCard.tsx`, `web/src/components/TicketList.tsx`,
  `web/src/pages/ArtistDashboard.tsx`, `web/src/pages/Home.tsx`,
  `web/src/pages/Purchase.tsx`, `web/src/services/api.ts`, `web/src/utils/tickets.ts`.
- Tests/operations: `tests/test_quantity_purchases.py`, `web/tests/tickets.test.mjs`,
  `scripts/migrate_quantity_inventory.py`, `scripts/test_quantity_live.py`, and
  this report. The pre-existing untracked Ticketmaster export script is untouched.
