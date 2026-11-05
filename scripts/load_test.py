"""Small load test for the ticketing API (standard library only, no pip install).

Examples (from the repo root):
  export API=https://xxxx.execute-api.us-east-1.amazonaws.com
  export TOKEN=<id token of fan@test.com>
  python3 scripts/load_test.py --path /events
  python3 scripts/load_test.py --path /recommendations --requests 300 --concurrency 10

Defaults are small on purpose: the Learner Lab has a limited budget.
Results are printed and appended to scripts/load_test_results.csv for the report.
"""
import argparse
import csv
import os
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime


def one_request(url, token):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
            status = resp.status
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception:
        status = 0  # network error or timeout
    return status, (time.perf_counter() - start) * 1000


def percentile(sorted_values, p):
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int(round(p / 100 * (len(sorted_values) - 1))))
    return sorted_values[index]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.environ.get("API", ""), help="API base URL (or env API)")
    ap.add_argument("--token", default=os.environ.get("TOKEN", ""), help="ID token (or env TOKEN)")
    ap.add_argument("--path", default="/events")
    ap.add_argument("--requests", type=int, default=200)
    ap.add_argument("--concurrency", type=int, default=10)
    args = ap.parse_args()

    if not args.api:
        raise SystemExit("Set the API url: export API=https://...  (or use --api)")
    if args.requests > 2000 or args.concurrency > 50:
        raise SystemExit("Too big for the Learner Lab budget: max 2000 requests and 50 threads")

    url = args.api.rstrip("/") + args.path
    print(f"GET {url}  requests={args.requests} concurrency={args.concurrency}")

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(lambda _: one_request(url, args.token), range(args.requests)))
    elapsed = time.perf_counter() - t0

    times = sorted(ms for _, ms in results)
    ok = sum(1 for s, _ in results if 200 <= s < 300)
    errors = len(results) - ok
    codes = {}
    for s, _ in results:
        codes[s] = codes.get(s, 0) + 1

    row = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "path": args.path,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "ok": ok,
        "errors": errors,
        "req_per_sec": round(len(results) / elapsed, 1),
        "avg_ms": round(statistics.mean(times), 1),
        "p50_ms": round(percentile(times, 50), 1),
        "p95_ms": round(percentile(times, 95), 1),
        "max_ms": round(times[-1], 1),
    }
    print("status codes:", codes)
    for k, v in row.items():
        print(f"{k:>12}: {v}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "load_test_results.csv")
    new_file = not os.path.exists(out)
    with open(out, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new_file:
            w.writeheader()
        w.writerow(row)
    print("saved to", out)


if __name__ == "__main__":
    main()
