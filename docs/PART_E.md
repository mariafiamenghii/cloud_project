# Part E: data, interests survey, recommendations, import, load test

Everything here runs against **your own** deployed copy (`terraform apply` in `infra/`).
Replace `API`, `CLIENT` and `POOL` with your own `terraform output` values.

```
cd infra
API=$(terraform output -raw api_url)
POOL=$(terraform output -raw user_pool_id)
CLIENT=$(terraform output -raw client_id)
cd ..
```

## Event categories

Every event has one category, stored lowercase in its `genre` field (the field
name is kept for compatibility). The list is shared by the event form, the
interests survey, the recommendations and the Barcelona import:

- ESADE association topics: consulting, finance, tech, entrepreneurship,
  marketing, luxury, sustainability, networking, sports, volunteering,
  social impact, career development, social events
- City and culture: food, music, festivals, workshops, theatre, art, talks, family,
  culture

Categories with several words are stored with one space (`social impact`).

The list lives in `CATEGORIES` (`web/src/utils/eventMedia.ts`) and in
`lambdas/create_event/categories.py`. `tests/test_categories.py` fails if they
differ. `POST /events` returns 400 for a category outside the list. Events saved
before the categories existed may still have a music genre (`jazz`, `rock`...):
they still display, and the recommendations treat them as `music`.

## 1. Sample events (plan B/C, works offline)
30 fictional ESADE association events (Finance Club, Tech Club, Luxury Club...)
in `data/sample_events.json`, covering every category. They are sold in the app.
```
python3 scripts/load_events.py
```

## 2. Barcelona city events (plan A, Open Data BCN)
No API key needed. `scripts/import_bcn_agenda.py` downloads the City Council's
cultural agenda (about 180 MB of JSON, updated daily) and maps its Catalan
category names to our categories: food, workshops, festivals (including
Christmas), art and museums, talks, theatre, music (including nightlife),
sports, tech, sustainability and family. Events in none of them are skipped.
```
python3 scripts/import_bcn_agenda.py --dry-run                         # prints what it would load
python3 scripts/import_bcn_agenda.py --file /tmp/agenda.json --dry-run # reuse a downloaded copy
python3 scripts/import_bcn_agenda.py                                   # loads into DynamoDB
```
Each category keeps its soonest events, up to `--per-category` (default 20); music
is capped at 15 because concerts are most of the agenda. A show repeated on several
days is kept once. Imported events have `source: barcelona_open_data`, `capacity: 0`
and an `externalUrl`: they are shown and recommended, but not sold in our app.
Entry marked "Lliure" is stored as free (`price: 0`). Images carry the attribution
the open data licence requires. Repeating the import never duplicates (the event id
is derived from the agenda's register id).

`scripts/import_ticketmaster.py` is the legacy import from before the platform
became an ESADE and Barcelona events platform. It is no longer part of the demo.

## 3. Interests survey and recommendations
Create a fan (same pattern as the README), then:
```
FAN=$(aws cognito-idp initiate-auth --auth-flow USER_PASSWORD_AUTH --client-id $CLIENT \
  --auth-parameters USERNAME=fan@test.com,PASSWORD=Test1234 --query 'AuthenticationResult.IdToken' --output text)

curl -X POST $API/preferences -H "Authorization: Bearer $FAN" -H "Content-Type: application/json" \
  -d '{"genres":["finance","networking"],"favoriteArtists":["ESADE Finance Club"],"city":"Barcelona","maxPrice":30}'

curl $API/recommendations -H "Authorization: Bearer $FAN"
```
In the web this is the **My Interests** page: the user picks topics (`genres` =
category values) and up to 5 associations they follow (`favoriteArtists`), chosen
from the fixed ESADE list (`ESADE_ASSOCIATIONS` in `web/src/utils/interests.ts`),
the associations that publish events, or typed in. Saved answers are loaded back,
so the survey can be edited later.

Score (`lambdas/recommend/index.py`): followed association +5, interest +3, same
city +2, price within budget +1. Only upcoming events; the 10 best are returned,
each with its reasons ("you're interested in finance", "by ESADE Finance Club,
which you follow", "in Barcelona", "fits your budget" or "free entry"). A followed
name also matches a longer association name ("Finance Club" matches "ESADE
Finance Club"). Without a survey, the soonest events are returned ("coming up soon").

Associations send `artist` (association name), `genre` (category) and `venue`
when they create an event (`POST /events`), so their events show up in
recommendations.

## 4. Load test and dashboard
```
python3 scripts/load_test.py --api $API --token $FAN --path /recommendations --requests 300 --concurrency 20
python3 scripts/load_test.py --api $API --token $FAN --path /events --requests 300 --concurrency 20
```
Max 2,000 requests and 50 threads (Learner Lab budget). Each run is appended to
`scripts/load_test_results.csv` (not committed).
The CloudWatch dashboard is `ticketing-dashboard` (CloudWatch -> Dashboards), created by `infra/monitoring.tf`.
