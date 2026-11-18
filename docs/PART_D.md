# Part D: purchase workflow, ticket and email

Part D is the fulfillment half of a purchase. Part C accepts the request and
puts it on SQS; the worker starts a **Step Functions** state machine that:

1. **ReserveSeat** – conditional hold on the `seats` table
2. **TakePayment** – simulated payment (see below)
3. **GenerateTicket** – issue a QR ticket and mark the seat `sold`
4. **SendEmail** – best-effort SES confirmation

On failure the state machine compensates per stage: a reservation failure
rejects the order, a payment failure releases the held seat, a post-payment
failure marks the order `REVIEW_REQUIRED` **without** freeing the paid seat, and
a notification failure still completes the purchase. Full state-transition
details are in [`INTEGRATION_PURCHASE_WORKFLOW.md`](INTEGRATION_PURCHASE_WORKFLOW.md).

Order states: `PENDING -> RESERVED -> PAID -> CONFIRMED` (plus `REJECTED`,
`FAILED`, `REVIEW_REQUIRED`). Seat states: `free -> held -> sold`. A `sold` seat
can never be re-reserved, so the platform does not oversell.

## Demo decisions and known limitations

These are deliberate MVP choices, called out here for the report and the demo.

### 1. The ticket is shown on the web, not emailed (SES is blocked)

Amazon SES is **blocked on the AWS Academy and ESADE Innovation Sandbox
accounts** (both `ses:VerifyEmailIdentity` and `ses:SendEmail` return
`AccessDenied` at the account level, independent of our IAM role). So:

- The `send_email` step is **best effort**: if SES fails or `notify_email` is
  empty, the purchase still completes and the order records
  `emailStatus = not_sent` with the reason in CloudWatch.
- The SES identity resource is only created when `notify_email` is set
  (`count = var.notify_email != "" ? 1 : 0`), so `terraform apply` succeeds on
  the lab accounts without it.
- As the real deliverable, the **website shows the QR ticket** once the order is
  `CONFIRMED`. The frontend polls `GET /orders/{orderId}` after the purchase and
  renders `qrUrl` / `qrPayload`. If the class later runs on an account where SES
  is allowed, set `notify_email` to a verified address and the email is sent in
  addition to the on-screen ticket.

`GET /orders/{orderId}` (Cognito-protected) returns only the caller's own order;
a different user gets `404` even with a valid orderId.

### 2. Seats are entered by hand (`1..capacity`); the `seats` table is not pre-seeded

We did **not** pre-generate one item per seat in the `seats` table. Instead:

- An event stores a `capacity`. Valid seat numbers are the integers
  `1..capacity`, entered by the buyer (and validated by the frontend,
  `create_purchase`, and `reserve_seat`).
- `reserve_seat` creates the seat item on first hold with a conditional write
  (hold if the seat is absent, free, an expired hold, or already held by the
  same order), and checks the number is within the event's capacity.

This keeps the demo simple and still prevents overselling. Pre-seeding a real
seat map (named seats, a seat picker) would be a separate feature; it is listed
as a limitation, not a bug.

### 3. Payment is simulated

`take_payment` does not call any payment provider. It records a deterministic
payment (stable `paymentId` and timestamp so retries are safe) and marks the
order `PAID`. A purchase can be forced to fail for the demo by sending
`{"forceFail": true}` in the order, which exercises the seat-release
compensation path. There is no real charge and therefore no refund API.

## Files

- `infra/workflow.tf` – the five workflow Lambdas, the STANDARD state machine,
  the optional SES identity, and the `GET /orders/{orderId}` read route.
- `lambdas/reserve_seat`, `take_payment`, `generate_ticket`, `send_email`,
  `release_seat` – the workflow steps (share `lambdas/workflow_common/purchase_common.py`).
- `lambdas/get_order` – the authenticated order-status read used by the website.
