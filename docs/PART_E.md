# Part E: data, survey, recommendations, import, load test

Everything here runs against **your own** deployed copy (`terraform apply` in `infra/`).
Replace `API`, `CLIENT` and `POOL` with your own `terraform output` values.

```
cd infra
API=$(terraform output -raw api_url)
POOL=$(terraform output -raw user_pool_id)
CLIENT=$(terraform output -raw client_id)
cd ..
```

## 1. Sample data (plan B/C, works offline)
30 fictional concerts in `data/sample_events.json`.
```
python3 scripts/load_events.py
```

## 2. Real concerts from Spain (plan A, Ticketmaster Discovery API)
1. Get a free key at https://developer.ticketmaster.com (My Apps -> Consumer Key).
2. Type the export line by hand and paste the key after the `=` (never commit it):
```
export TM_API_KEY=
python3 scripts/import_ticketmaster.py --dry-run          # prints what it would load
python3 scripts/import_ticketmaster.py                    # loads into DynamoDB
python3 scripts/import_ticketmaster.py --city Barcelona   # extra events for one city
```
Imported events have `source: ticketmaster`, `capacity: 0` and an `externalUrl`.
They are shown and recommended, but not sold in our app. Repeating the import never duplicates
(the event id is derived from the Ticketmaster id). Free quota: 5,000 calls/day, 5 per second.

## 3. Taste survey and recommendations
Create a fan (same pattern as the README), then:
```
FAN=$(aws cognito-idp initiate-auth --auth-flow USER_PASSWORD_AUTH --client-id $CLIENT \
  --auth-parameters USERNAME=fan@test.com,PASSWORD=Test1234 --query 'AuthenticationResult.IdToken' --output text)

curl -X POST $API/preferences -H "Authorization: Bearer $FAN" -H "Content-Type: application/json" \
  -d '{"genres":["indie","jazz"],"favoriteArtists":["Pols de Marbre"],"city":"Barcelona","maxPrice":30}'

curl $API/recommendations -H "Authorization: Bearer $FAN"
```
Score: favourite artist +5, genre +3, same city +2, price within budget +1. Only upcoming events.
Without a survey, the soonest events are returned.

Artists can now send optional `artist`, `genre` and `venue` when they create an event
(`POST /events`), so their events show up in recommendations.

## 4. Load test and dashboard
```
python3 scripts/load_test.py --api $API --token $FAN --path /recommendations --requests 300 --concurrency 20
python3 scripts/load_test.py --api $API --token $FAN --path /events --requests 300 --concurrency 20
```
Max 2,000 requests and 50 threads (Learner Lab budget). Each run is appended to
`scripts/load_test_results.csv` (not committed).
The CloudWatch dashboard is `ticketing-dashboard` (CloudWatch -> Dashboards), created by `infra/monitoring.tf`.
