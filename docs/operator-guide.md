# Operator Guide

A runbook for driving the fleet end-to-end: set up, deploy, inspect, break, roll out,
roll back, and tear down. Everything runs locally with Docker Compose.

## Prerequisites

- Docker + Docker Compose v2 (`docker compose version`)
- `curl` and `jq` (used for inspection)
- `python3` (used by `ops-canary.sh`)
- Optional, for running the app outside Docker: [`uv`](https://docs.astral.sh/uv/)

## City → port map

| City      | Port | City      | Port |
|-----------|------|-----------|------|
| vancouver | 8001 | frankfurt | 8004 |
| toronto   | 8002 | singapore | 8005 |
| london    | 8003 |           |      |

All endpoints are `http://localhost:<port>` → `/health`, `/ready`, `/metrics`, `/infer`.

---

## 1. Set up the environment

```bash
# from the repo root
cp /dev/null .env 2>/dev/null || true      # optional: start with empty fleet overrides
# NOTE: .env currently sets DEGRADED_MODE=true (whole fleet misbehaves).
# Remove or set it to false for a healthy baseline:
echo 'DEGRADED_MODE=false' > .env

# Build the image (tagged worktrial-sre:latest via the vancouver service)
docker compose build
```

To run a single instance without Docker (quick sanity check):

```bash
uv sync
LOCATION=vancouver BASE_LATENCY_MS=120 uv run fastapi run app/main.py --port 8001
```

## 2. Deploy the system

```bash
docker compose up -d          # start all 5 cities
docker compose ps             # confirm they're up
```

Each city warms up for ~2s. `/health` is immediately `200`; `/ready` returns `503`
until warmup finishes, then `200`.

## 3. Inspect health / performance

Single city:

```bash
curl -s localhost:8001/health  | jq
curl -s localhost:8001/ready   | jq
curl -s localhost:8001/metrics | jq
```

Send some inference traffic (metrics are computed over the last 200 requests, so they
need traffic to be meaningful):

```bash
for i in $(seq 1 30); do
  curl -s -o /dev/null -X POST localhost:8001/infer \
    -H 'content-type: application/json' -d '{"prompt":"hello"}'
done
```

**Fleet status table** — poll every city at once:

```bash
for p in 8001 8002 8003 8004 8005; do
  curl -s "localhost:$p/metrics" | jq -r \
    '[.location, .version, .request_count, (.error_rate*100|floor|tostring+"%"),
      (.p95_ms|floor|tostring+"ms"), (.gpu_utilization*100|floor|tostring+"%")]
     | @tsv'
done | column -t -N CITY,VERSION,REQS,ERR_RATE,P95,GPU
```

## 4. Simulate failure

Two ways to make a city go "up but bad" (alive, but slow and erroring):

**A. During a canary** (recommended — self-contained and auto-reverts):

```bash
./ops-canary.sh v2 toronto --bad     # deploys v2 to toronto with DEGRADED_MODE=true
```

The `--bad` flag forces the new version into degraded mode; the health gate will
catch it and roll toronto back automatically (see §6).

**B. Manually** — recreate one city in degraded mode:

```bash
docker compose up -d --no-deps -e DEGRADED_MODE=true london
curl -s localhost:8003/metrics | jq '{error_rate, p95_ms}'   # elevated error rate + tail
```

Fleet-wide failure for a demo: set `DEGRADED_MODE=true` in `.env` and
`docker compose up -d`.

## 5. Perform a rollout (canary with health gate)

Roll a new version to **one** city and let the gate decide if it's safe to go wider:

```bash
./ops-canary.sh v2 vancouver         # canary v2 on vancouver
```

What happens:
1. Records vancouver's current version (rollback target).
2. Deploys `v2` to **only** vancouver.
3. Waits for `/ready` (up to ~15s).
4. Sends 25 probe requests to populate `/metrics`.
5. Evaluates the gate: **health 200 AND error_rate ≤ 5%**.
   - **PASS** → vancouver stays on `v2`; you may now roll the other cities.
   - **FAIL** → vancouver is rolled back automatically.

Roll the rest of the fleet once the canary passes (repeat per city, or script it):

```bash
for city in toronto london frankfurt singapore; do
  ./ops-canary.sh v2 "$city" || { echo "STOP: $city failed the gate"; break; }
done
```

## 6. Perform a rollback

Rollback is automatic on gate failure. To roll a city back manually, re-canary it onto
the known-good version (the gate will pass and it settles there):

```bash
./ops-canary.sh v1 vancouver         # revert vancouver to v1
```

Or directly via Compose (immediate, no gate):

```bash
docker compose up -d --no-deps -e VERSION=v1 -e DEGRADED_MODE=false vancouver
curl -s localhost:8001/health | jq .version     # confirm -> "v1"
```

## 7. Tear everything down

```bash
docker compose down            # stop + remove all 5 cities
docker compose down --rmi local -v   # also remove the built image and volumes
```

---

## Troubleshooting

| Symptom                                   | Likely cause / fix                                            |
|-------------------------------------------|--------------------------------------------------------------|
| `/ready` stuck on 503                     | Still within the ~2s warmup; wait and retry.                 |
| `/metrics` shows `request_count: 0`       | No traffic yet — send some `/infer` requests first.          |
| Every city is erroring / slow             | `.env` has `DEGRADED_MODE=true`; set to false and redeploy.  |
| Canary reports FAIL immediately           | Ran with `--bad`, or the target version is genuinely broken. |
| `unknown city` from `ops-canary.sh`       | Use one of: vancouver, toronto, london, frankfurt, singapore.|
| Port already in use on `up`               | Another process holds 8001–8005; free it or stop old stack.  |
