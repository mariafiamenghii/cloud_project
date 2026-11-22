# Event images, official prices and Catalan

## Implementation

Ticketmaster imports use the official Discovery v2 search, detail and event-image
endpoints. Images are ranked by non-fallback status, landscape aspect ratio,
proximity to 16:9 and suitable resolution. The URL, dimensions, fallback flag and
provided attribution are stored. Images stay on the provider's host; none are
copied into S3. Cards use lazy images, cover sizing, fixed-height containers and
a music-note fallback on missing/broken images. Credits are displayed when given.

Official priceRanges are filtered to finite, non-negative minima with a currency.
EUR is preferred for Spain; otherwise one available currency is selected without
comparing amounts across currencies. The lowest minimum within that currency is
stored as price/currency. Cards use Intl currency formatting. Missing external
prices display **See price on Ticketmaster**. Existing valid prices are never
erased when the API omits prices. Ticketmaster events remain external listings.

Both Home and Recommendations propagate the shared image/currency fields into
EventCard. The actual genre remains visible; only `catalan` is labelled Catalan.
Artist Dashboard and Survey share the existing ten genres plus Catalan, storing
lowercase `catalan`. Existing recommendation scoring already matches this value;
its application logic is unchanged.

## Artist uploads

POST `/event-images/uploads` requires a Cognito JWT and artist/admin membership.
It returns a five-minute presigned S3 POST with a random owner-prefixed key,
an exact accepted content type and a 1-byte–5-MB size condition. React sends the
selected local file directly to S3. The form validates JPEG/PNG/WebP and size,
previews the local file, and supports removal/replacement. Images are optional.

POST `/events` accepts `imageKey`, never arbitrary `imageUrl` or `imageObjectKey`.
It checks the raw upload belongs to the authenticated artist, enforces actual
size/type, verifies and fully decodes the bytes with pinned Pillow, limits pixels,
applies orientation, strips metadata by re-encoding and bounds output size. Only
then does it write a private canonical WebP and associate it with the new event.
Existing event fields and quantity inventory initialization remain unchanged.

GET `/event-images/{eventId}` reads the event's published association before
serving bytes from private S3. The event URL is stable and does not contain an
expiring signature. Unassociated objects cannot be served. S3 public access is
blocked, ACLs are disabled, default encryption is enabled and upload CORS permits
only POST from the existing main Amplify origin. Raw uploads expire after one day.
Successful publication removes the raw upload; failed event writes attempt to
remove the canonical object. Failed cleanup leaves only a private orphan, never
a public image. No new IAM grants are introduced; Academy's existing LabRole is
reused.

The image-validation layer is built reproducibly with:

```sh
python3.12 scripts/build_image_layer.py
```

It downloads the pinned Linux CPython 3.12 wheel and writes an ignored ZIP into
infra. Terraform CI builds this artifact before validation. Local Python cache
files are excluded from the affected directory-based Lambda archives.

## Safe import and backfill

The importer no longer replaces existing records through batch put operations.
New records use conditional create. Existing imported records receive metadata-
only conditional updates. Inventory fields, event IDs, source, links, orders and
tickets cannot be changed by that update helper. Compare-and-set conditions
detect concurrent metadata changes instead of overwriting them.

Existing imports without a Ticketmaster ID are matched using their original
deterministic UUID mapping against official city searches. Matched records gain
the official ID for subsequent detail lookups. Unmatched records are retained.
No name-based guessing, scraping or duplicate creation is used.

```sh
python3.12 scripts/import_ticketmaster.py --backfill --dry-run --key-file /tmp/ticketmaster-api-key
python3.12 scripts/import_ticketmaster.py --backfill --apply --key-file /tmp/ticketmaster-api-key
```

The key stays in its local permission-600 file or TM_API_KEY; it is never printed
or committed. API errors are sanitized so they cannot expose keyed query URLs.
The client rate-limits requests and backs off on 429. Refresh metadata periodically
within your API quota; honor provider removal requests and do not retain provider
content indefinitely. Stored ticket history must not be deleted during refresh.

References: [Discovery API](https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/),
[Ticketmaster terms](https://developer.ticketmaster.com/support/terms-of-use/).

## Validation and deployment record

Local checks: **75 Python tests**, **13 frontend tests**, ESLint, TypeScript/Vite,
Terraform format/validation and whitespace checks passed. Tests cover all three
upload formats, actual-content rejection, ownership, fan/unauthenticated access,
size/type limits, missing optional image, failed upload recovery, private orphan
handling, safe metadata backfill, image selection, price/currency selection,
Catalan matching and the existing purchase regressions.

Official API dry run on 22 November 2026: 272 existing imports inspected,
262 image updates available, ten unavailable from current official results.
Search and detail responses supplied no prices for these existing Spanish
listings. No prices were invented and no existing values were cleared.

The user approved the reviewed plan: **12 additions, one event-creation Lambda
update, zero deletions**. No purchase Lambda, SQS mapping, Step Functions, orders,
tickets or inventory resources are changed. Recommendations only gains an archive
cache exclusion; its deployed package should remain unchanged.

Initial deployment was blocked before creating resources: both s3:CreateBucket
and lambda:PublishLayerVersion were denied by Academy's `voc-cancel-cred` policy.
Resume the lab and refresh local CLI credentials before retrying. Approval has
already been granted; refresh/review the plan with the restored credentials.
Do not merge an upload-enabled frontend until its backend is deployed.

`scripts/test_event_media_live.py` is the explicit live verification script. It
creates isolated test accounts/events, exercises direct S3 uploads and stable
image reads, verifies Catalan preferences/recommendations, then buys one and four
tickets on a new test event and checks five unique tickets and inventory 95.
It disables its test accounts afterwards. Existing data is never overwritten.

## Changed files

- `.github/workflows/terraform-ci.yml`
- `infra/images.tf`, `infra/events_api.tf`, `infra/recommendations.tf`
- `lambdas/event_images/index.py`, `lambdas/create_event/index.py`,
  `lambdas/create_event/image_validation.py`
- `scripts/import_ticketmaster.py`, `scripts/ticketmaster_media.py`,
  `scripts/build_image_layer.py`, `scripts/image-requirements.txt`,
  `scripts/test_event_media_live.py`
- `tests/test_event_media.py`, `tests/requirements.txt`
- `web/src/components/EventCard.tsx`, `web/src/pages/ArtistDashboard.tsx`,
  `web/src/pages/Home.tsx`, `web/src/pages/Recommendations.tsx`,
  `web/src/pages/Survey.tsx`, `web/src/services/api.ts`, `web/src/utils/eventMedia.ts`,
  `web/src/App.css`, `web/tests/eventMedia.test.mjs`, and this report.

The pre-existing untracked `scripts/export_ticketmaster.py` is preserved.
