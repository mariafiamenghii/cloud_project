# Event images and official prices

> Update: the external events shown today come from the Barcelona city agenda
> (`scripts/import_bcn_agenda.py`, see `docs/PART_E.md`). Their images stay on
> the City Council's host and carry its attribution; missing prices show
> **See price on the official site**. The Ticketmaster parts below describe the
> legacy import and are kept as a record of how it was built.

## Implementation

Ticketmaster imports use the official Discovery v2 search, detail and event-image
endpoints. Images are ranked by non-fallback status, landscape aspect ratio,
proximity to 16:9 and suitable resolution. The URL, dimensions, fallback flag and
provided attribution are stored. Images stay on the provider's host; none are
copied into S3. Cards use lazy images, cover sizing, fixed-height containers and
a neutral star fallback on missing/broken images. Credits are displayed when given.

Official priceRanges are filtered to finite, non-negative minima with a currency.
EUR is preferred for Spain; otherwise one available currency is selected without
comparing amounts across currencies. The lowest minimum within that currency is
stored as price/currency. Cards use Intl currency formatting. Missing external
prices display **See price on Ticketmaster**. Existing valid prices are never
erased when the API omits prices. Ticketmaster events remain external listings.

Both Home and Recommendations propagate the shared image/currency fields into
EventCard. Cards show the event's category by its display name ("finance" ->
"Finance"); old music genres are shown as stored. The Association Dashboard and
the My Interests survey share the `CATEGORIES` list (see `docs/PART_E.md`).

## Association uploads

POST `/event-images/uploads` requires a Cognito JWT and membership of the
`artist` (association) or `admin` group.
It returns a five-minute presigned S3 POST with a random owner-prefixed key,
an exact accepted content type and a 1-byte–5-MB size condition. React sends the
selected local file directly to S3. The form validates JPEG/PNG/WebP and size,
previews the local file, and supports removal/replacement. Images are optional.

POST `/events` accepts `imageKey`, never arbitrary `imageUrl` or `imageObjectKey`.
It checks the raw upload belongs to the authenticated association, enforces actual
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

Academy permits S3 creation and normal object access but denies
`GetBucketObjectLockConfiguration` through its organization policy. The standard
Terraform bucket resource reads this unconditionally. The new bucket was retained
with a declarative `removed` block (`destroy=false`) and is referenced through a
HeadBucket-based data source. All five bucket security/configuration resources
remain Terraform-managed. Nothing was deleted or recreated. This exception is
limited to this new base bucket; existing infrastructure ownership is unchanged.
If a lab reset removes it, run `python3.12 scripts/ensure_image_bucket.py` before
planning/applying Terraform. The helper creates only a missing private bucket and
never deletes one. Terraform 1.7+ is required for the explicit retention block.

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

The approved backfill subsequently applied **262 image updates**, with **zero
conflicts**. It verified **30 historical orders**, **21 issued ticket records**,
**14 internal event records**, and all **272 imported event IDs, links, inventory
and other non-media fields** unchanged. Ten imports were retained without a new
image; no official prices were available. These counts precede new live test
fixtures and do not include them.

The user approved the reviewed plan: **12 additions, one event-creation Lambda
update, zero deletions**. No purchase Lambda, SQS mapping, Step Functions, orders,
tickets or inventory resources are changed. Recommendations only gains an archive
cache exclusion; its deployed package should remain unchanged.

An initial attempt was blocked before creating resources by Academy's
`voc-cancel-cred` policy. The user resumed the lab and refreshed local credentials.
The layer and bucket were then created, followed by the retained-bucket workaround
above and the remaining ten resources. Backend deployment completed with one
event-creation Lambda update and no resource deletion. No purchase Lambda was
updated.

`scripts/test_event_media_live.py` is the explicit live verification script. It
creates isolated test accounts/events, exercises direct S3 uploads and stable
image reads, verifies Catalan preferences/recommendations, then buys one and four
tickets on a new test event and checks five unique tickets and inventory 95.
It disables its test accounts afterwards. Existing data is never overwritten.

The live script passed on 22 November 2026. Published image fixtures:
`2ca869e5-de1d-4a87-ba5f-87b51b43f5c3` (JPEG),
`7bea8038-8cda-4bea-8ac5-45d6c597a97a` (PNG), and
`83f91453-7afb-4a93-a0ca-b5e1b28f09cb` (WebP). All served canonical WebP images
through the stable API endpoint, while direct anonymous S3 reads returned 403.
Unauthenticated/fan uploads, unsupported types, oversized authorization,
cross-artist attachment and arbitrary external references were rejected. Optional
image creation and Catalan preference/recommendation matching passed. Both test
accounts were disabled afterwards.

Purchases on the first fixture confirmed quantities one and four, producing five
distinct ticket IDs. Orders:
`purchase-06ec1c6c42a69f60cf48f6cba95cfffab3c4a65b46da95e4c9a0c7a429986db5` and
`purchase-787cffc4316045111e913bd6e350f7df176907587482974b765f3ea850f40e57`.
Final fixture inventory: sold 5, reserved 0, available 95.

## Changed files

- `.github/workflows/terraform-ci.yml`
- `infra/images.tf`, `infra/events_api.tf`, `infra/recommendations.tf`, `infra/providers.tf`
- `lambdas/event_images/index.py`, `lambdas/create_event/index.py`,
  `lambdas/create_event/image_validation.py`
- `scripts/import_ticketmaster.py`, `scripts/ticketmaster_media.py`,
  `scripts/build_image_layer.py`, `scripts/image-requirements.txt`,
  `scripts/test_event_media_live.py`, `scripts/ensure_image_bucket.py`
- `tests/test_event_media.py`, `tests/requirements.txt`
- `web/src/components/EventCard.tsx`, `web/src/pages/ArtistDashboard.tsx`,
  `web/src/pages/Home.tsx`, `web/src/pages/Recommendations.tsx`,
  `web/src/pages/Survey.tsx`, `web/src/services/api.ts`, `web/src/utils/eventMedia.ts`,
  `web/src/App.css`, `web/tests/eventMedia.test.mjs`, and this report.

The pre-existing untracked `scripts/export_ticketmaster.py` is preserved.
