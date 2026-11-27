# Part D: purchase workflow, ticket and email

Part D is the fulfilment half of a purchase. A student buys tickets for an event
published by an ESADE association; Part C accepts the request and puts it on
SQS; the worker starts a **Step Functions** state machine that:

1. **ReserveSeat** – reserves the requested number of tickets (the state keeps
   its original name; purchases are now general admission, see below)
2. **TakePayment** – simulated payment (see below)
3. **GenerateTicket** – issues one QR ticket per unit and marks them sold
4. **SendEmail** – best-effort SES confirmation

On failure the state machine compensates per stage: a reservation failure
rejects the order, a payment failure releases the held tickets, a post-payment
failure marks the order `REVIEW_REQUIRED` **without** releasing the paid
tickets, and a notification failure still completes the purchase. Full details
are in [`QUANTITY_PURCHASES.md`](QUANTITY_PURCHASES.md) and
[`INTEGRATION_PURCHASE_WORKFLOW.md`](INTEGRATION_PURCHASE_WORKFLOW.md).

Order states: `PENDING -> RESERVED -> PAID -> CONFIRMED` (plus `REJECTED`,
`FAILED`, `REVIEW_REQUIRED`). Each event keeps `capacity = sold + reserved +
available`, and every counter change happens in the same DynamoDB transaction
as the order change, so the platform never sells more tickets than the capacity
and a retried step never counts twice.

Only events published on FRONT ROW are sold. Barcelona city events
(`source: barcelona_open_data`) have capacity 0 and are only shown with a link.

## Demo decisions and known limitations

These are deliberate MVP choices, called out here for the report and the demo.

### 1. The ticket is shown on the web, not emailed (SES is blocked)

Amazon SES is **blocked on the AWS Academy and ESADE Innovation Sandbox
accounts** (`ses:VerifyEmailIdentity` and `ses:SendEmail` return `AccessDenied`
at the account level, independent of our IAM role). The teacher accepted this.

- The `send_email` step is **best effort**: if SES fails or `notify_email` is
  empty, the purchase still completes and the order records
  `emailStatus = not_sent` with the reason in CloudWatch.
- The SES identity resource is only created when `notify_email` is set
  (`count = var.notify_email != "" ? 1 : 0`), so `terraform apply` succeeds on
  the lab accounts without it.
- As the real deliverable, the **website shows the tickets**: one QR code per
  ticket, drawn in the browser from its `qrPayload`. The Purchase page polls
  `GET /orders/{orderId}` until the order is `CONFIRMED`, and **My Tickets**
  (`GET /orders`) lists every order later. If the course runs on an account where
  SES is allowed, set `notify_email` to a verified address and the email is sent
  in addition to the on-screen tickets.

`GET /orders/{orderId}` (Cognito-protected) returns only the caller's own order;
a different user gets `404` even with a valid orderId.

### 2. General admission, no numbered seats

The first version asked the buyer for a seat number (`1..capacity`) and held that
seat in the `seats` table. The current version sells **a quantity** (1–20 tickets
per order) from the event's `available` counter, which suits association events
(talks, networking nights, parties) better than numbered seats. Old seat-based
orders keep their original single ticket and QR code. A seat map would be a
separate feature; it is listed as a limitation, not a bug.

### 3. Payment is simulated

`take_payment` does not call any payment provider. It records a deterministic
payment (stable `paymentId` and timestamp, so retries are safe) and marks the
order `PAID`. There is no real charge and therefore no refund API. A `forceFail`
flag in the workflow input makes the payment fail; the automated tests use it to
check that held tickets are released. It cannot be sent through the public
purchase API (`POST /purchases` accepts only `eventId`, `quantity` and
`idempotencyKey`).

## Files

- `infra/workflow.tf` – the workflow Lambdas, the STANDARD state machine, the
  optional SES identity, and the `GET /orders/{orderId}` read route.
- `lambdas/reserve_seat`, `take_payment`, `generate_ticket`, `send_email`,
  `release_seat` – the workflow steps (they share `lambdas/workflow_common/`).
- `lambdas/get_order` – the authenticated order-status read used by the website.
