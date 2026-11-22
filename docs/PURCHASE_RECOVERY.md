# Purchase recovery — 22 November 2026

## Root cause and evidence

The deployed SQS event source mapping `87d5e171-1207-46fb-8e4c-3e970145781b`
was **Disabled**, with `StateTransitionReason=USER_INITIATED`. At the initial
inspection the purchase queue contained seven visible messages, no in-flight
messages, and the DLQ was empty. Seven orders had `orderStatus=PENDING` and
`dispatchStatus=PENDING`; no executions existed for these orders. CloudTrail's
lookup returned no matching update events, so the actor and reason for disabling
the mapping could not be established.

Example: `purchase-0c505c8589da94c3ac29c43a1779b517e36ee6d0cef16cd84c4715a2644de009`
was PENDING before recovery and CONFIRMED/paid/issued/STARTED afterwards.

The deployed `GET /orders/{orderId}` route exists, uses Cognito JWT authorizer
`86zaag`, integrates with `ticketing-get-order`, and has a matching Lambda invoke
permission. The configured issuer and client match Amplify's environment.
Actual read-only response checks distinguished these cases:

| Request | Response |
| --- | --- |
| HTTP GET to an existing protected orders route without a token | 401, `{"message":"Unauthorized"}` |
| HTTP GET to a nonexistent API route | 404, `{"message":"Not Found"}` |
| Direct invocation of the order reader with a missing order | 404, `{"error":"Order not found"}` |
| Direct invocation with an actual pending order and its owner's claim | 200, `orderStatus=PENDING` |

These findings rule out a missing deployed GET route as the current blocker.
Earlier intake versions relied on the worker to create the record, so a stalled
consumer could also produce missing-order 404s. Main already includes commit
`273d15d`, persisting the order before enqueueing; both intake and worker deployed
source files match that code. No historical authenticated HTTP 404 body was
available to conclusively attribute every previously observed 404.

All eight purchase-path Lambda packages were downloaded and their Python source
files compared byte-for-byte with main. All matched. All functions were Active
and used LabRole. Their environment variables contain table names, the queue URL,
workflow ARN, hold duration, and notification configuration, with no manually
configured AWS access keys. Runtime credentials come from the execution role.

## Approved infrastructure recovery

The user approved processing the queued purchases. Applied a reviewed targeted
Terraform plan: 0 additions, 2 in-place changes, 0 deletions.

- Re-enabled the existing SQS event source mapping (`enabled=true` already in Terraform).
- Reconciled the worker's stale Terraform code hash by deploying the same package.

The queue drained and all pending orders were dispatched. Three of the original
seven became CONFIRMED; the other four became REJECTED during reservation.
Further requests arrived during investigation and also reached terminal states.
An inspected rejection reports `SeatUnavailable`; orders were never forced into
CONFIRMED. The DLQ remained empty. No historical order was manually edited.

A subsequent full read-only plan reported only the intake's stale code hash and
an Amplify access-token difference (0 additions/deletions). It was not applied.
Plan files are local under `/tmp` and must not be committed because plans can
contain credentials and state data.

## Live end-to-end verification

Used the existing signed-in browser session on
`https://main.d33683xv54jew.amplifyapp.com` to create an isolated internal event:

- Event: `QR Recovery Test 2026-11-22`
- Event ID: `6e067528-657d-4981-aef1-c49bc025d79c`
- Date: 30 November 2026; price: EUR 0; capacity: 3
- Fresh seat: 1
- Order: `purchase-064f7dd6fa704f3e4b6220a25905df6d47c619e77de15f6572fcb4cbc70c54dc`

The UI submitted the purchase through the protected API, polled the owner's
order, displayed Ticket confirmed, and visibly loaded the QR image. The matching
Step Functions execution SUCCEEDED on 22 November at 12:30:13 Europe/Madrid.
DynamoDB recorded the matching sold seat. This verifies the deployed workflow
independently of a local build. Payment is simulated and no card was charged.
The test event and its order remain available for audit; seat 1 must not be reused.

## Code safeguards and checks

- `web/src/services/http.ts`: preserve HTTP status/body and distinguish the
  Lambda's missing-order response from a missing API Gateway route.
- `web/src/services/api.ts`: apply typed HTTP handling and verify the returned
  order ID matches the requested one.
- `web/src/pages/Purchase.tsx`: show permanent status-read errors; allow checking
  the same order again after polling ends; remove the nonexistent My Tickets
  instruction; report image-load failures and derive a QR URL from a payload
  when the URL is absent; align demo-mode detection with App.tsx.
- `web/tests/http.test.mjs`: exercise response bodies, auth errors, gateway 404s,
  non-JSON errors and successful ticket responses.
- `tests/test_workflow_integration.py`: stop ASL extraction at the state machine's
  closing brace rather than including the later GET-order Terraform resources.

Checks: ESLint, TypeScript, Vite production build, six frontend tests, 54 Python
tests, Terraform validate/fmt, and live browser purchase all passed. Vite retains
its existing large-bundle warning. Ticketmaster imports/links and styles were
not changed.

## Future Academy sessions

1. Start the lab. Refresh the local Academy CLI access key, secret key and session
   token only when needed for CLI/Terraform. Use `/usr/local/bin/aws`, not the
   broken Homebrew CLI. Never copy credentials into Lambda, frontend or Git.
2. Check identity with `/usr/local/bin/aws sts get-caller-identity --region us-east-1`.
3. Check the mapping before a demo:

   ```sh
   /usr/local/bin/aws lambda get-event-source-mapping --uuid 87d5e171-1207-46fb-8e4c-3e970145781b --region us-east-1
   /usr/local/bin/aws sqs get-queue-attributes --queue-url https://sqs.us-east-1.amazonaws.com/089694126398/ticketing-purchase-queue --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --region us-east-1
   ```

4. Expect mapping State=Enabled. If disabled, inspect the backlog and a Terraform
   plan before enabling it: doing so processes waiting purchases. Do not purge
   queues, replay failed purchases under new execution IDs, or manually confirm
   orders. Queue retention is four days, so don't leave accepted work stalled.
5. If the lab actually resets resources, inspect Terraform and rebuild through
   the established deployment process; refresh Amplify's API/Cognito values only
   if resource IDs changed. There is no evidence this incident was a resource reset.

No runtime credential refresh is required for Lambda. Buyers may need to sign
in again when their Cognito session expires. Email remains disabled/simulated
because SES is unavailable. QR images still depend on api.qrserver.com.
