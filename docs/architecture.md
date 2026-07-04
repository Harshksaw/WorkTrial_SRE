# Architecture

## Overall system design

The system is a small SRE playground that models a globally-distributed inference
fleet. There is exactly **one** application — a fake inference service — deployed as
**five independent instances** ("cities"). Everything else (deployment, monitoring,
rollout) is built around driving and observing those five instances.

```
        ┌──────────────────────────────────────────────┐
        │  Operator tooling                            │
        │   • docker compose  (deploy / status / down) │
        │   • ops-canary.sh   (gated rollout+rollback) │
        │   • curl + jq loop  (monitoring)             │
        └───────────────────┬──────────────────────────┘
                            │  docker compose / HTTP
                            ▼
   ┌──────────┬──────────┬──────────┬──────────┬──────────┐
   │ vancouver│  toronto │  london  │ frankfurt│ singapore│
   │  :8001   │  :8002   │  :8003   │  :8004   │  :8005   │
   └──────────┴──────────┴──────────┴──────────┴──────────┘
     one FastAPI image (worktrial-sre:latest), container port 80
     endpoints: /health · /ready · /metrics · /infer
```

The application lives in `app/main.py`. It is deliberately a single file: the whole
point is to *simulate* a service with realistic operational surfaces (liveness,
readiness, metrics, latency, errors), not to build real ML infrastructure.

### The service surface

| Endpoint   | Method | Purpose                                                        |
|------------|--------|----------------------------------------------------------------|
| `/health`  | GET    | Liveness — process is up. Returns `location`, `version`.        |
| `/ready`   | GET    | Readiness — 503 during warmup, 200 once warm.                  |
| `/metrics` | GET    | Request count, error rate, p50/p95/p99 latency, GPU util.      |
| `/infer`   | POST   | Simulated inference; applies latency + error behavior.         |

Liveness and readiness are **separate on purpose**: on startup a background task
(`_warmup`) sleeps ~2s, so `/health` is `200` immediately but `/ready` returns `503`
until warmup completes. This lets a rollout wait for a city to actually be serving
before trusting its metrics.

## How locations are simulated

All five cities run the **same image**; a city is nothing more than a set of
environment variables. The service reads its entire personality from env at startup
(`app/main.py`):

| Variable          | Default | Meaning                                                     |
|-------------------|---------|-------------------------------------------------------------|
| `LOCATION`        | `local` | City name echoed in every response.                         |
| `VERSION`         | `v1`    | Deployed version — the unit a rollout moves.                |
| `BASE_LATENCY_MS` | `100`   | Baseline inference latency.                                 |
| `TAIL_LATENCY_MS` | `0`     | Extra latency added to a fraction of requests (the tail).   |
| `ERROR_RATE`      | `0.0`   | Fraction of requests that fail with HTTP 500.               |
| `DEGRADED_MODE`   | `false` | "Something is wrong here" switch (see below).               |

`docker-compose.yml` gives each city a distinct `LOCATION` and `BASE_LATENCY_MS`,
which is how geography is faked — closer/faster vs. farther/slower:

| City      | Port | BASE_LATENCY_MS |
|-----------|------|-----------------|
| vancouver | 8001 | 120             |
| toronto   | 8002 | 160             |
| london    | 8003 | 220             |
| frankfurt | 8004 | 200             |
| singapore | 8005 | 300             |

**Degraded mode** is the failure primitive. When `DEGRADED_MODE=true`, `/infer`
forces `error_rate >= 25%`, raises tail latency to at least the base latency, and
bumps the tail probability from 10% to 70% — i.e. the city stays *alive* (health 200)
but *unhealthy* (slow and erroring). That distinction — up but bad — is exactly what
the readiness/metrics split and the rollout health gate exist to catch.

## How deployment works

Deployment is plain **Docker Compose**. One image, five services:

- The image is built once and tagged `worktrial-sre:latest`. The `vancouver` service
  carries `build: .`, so `docker compose build` (or `up --build`) produces the image;
  the other four reference the same tag and reuse it — no rebuild per city.
- The `Dockerfile` uses `python:3.12-slim`, installs deps with `uv sync --frozen`
  (reproducible from `uv.lock`), and runs `fastapi run app/main.py` on container
  port 80. Compose maps host ports 8001–8005 → 80.
- `.env` provides fleet-wide overrides (e.g. `DEGRADED_MODE=true` to make the whole
  fleet misbehave for a demo).

`docker compose up -d` = deploy; `docker compose ps` = status; `docker compose down`
= teardown. There is no bespoke deploy script because Compose already is one.

## How monitoring works

Monitoring is pull-based: poll every city's `/health` and `/metrics` and render a
table. `/metrics` is computed from in-process state in `app/main.py`:

- a `deque(maxlen=200)` of the most recent request latencies,
- running `REQUEST_COUNT` and `ERROR_COUNT`,
- percentiles (`p50/p95/p99`) computed on demand from the deque,
- a simulated `gpu_utilization` (random 0.30–0.95) to make the table feel alive.

Because the window is the last 200 requests, the numbers are meaningless without
traffic — which is why the rollout **generates its own probe load** before reading
the gate (see below). A simple monitoring loop is a `for` over ports 8001–8005 doing
`curl .../metrics | jq` (see the Operator Guide).

## How rollout / rollback works

Rollout is a **canary with a health gate**, implemented in `ops-canary.sh`. The design
goal is a blast radius of *exactly one city*: prove a version on one city before it is
allowed anywhere else, and undo it automatically if it misbehaves.

```
canary <version> [city=vancouver] [--bad]

1. Read the city's CURRENT version from /health  → this is the rollback target.
2. Deploy <version> to ONLY that city, via a temporary compose override
   (docker compose up -d --no-deps <city>). --bad also sets DEGRADED_MODE=true
   to simulate a broken build.
3. Wait for /ready to return 200 (up to ~15s). Never ready → roll back, exit 1.
4. Fire 25 probe POSTs at /infer so /metrics reflects the new version.
5. Evaluate the GATE:  health == 200  AND  error_rate <= 5%.
6. PASS → leave the city on <version>, report "safe to roll wider", exit 0.
   FAIL → redeploy the previous version to the city, exit 1.
```

**Rollback** is the same deploy mechanism in reverse: re-apply `OLD_VERSION` (captured
in step 1) with `DEGRADED_MODE=false`. It runs automatically on gate failure, and can
be invoked manually the same way. The other four cities are never touched, so a bad
canary is contained.

The override is written with `mktemp`, applied with `--no-deps` (so only the target
city is recreated), then deleted — the base `docker-compose.yml` stays clean and the
change is expressed purely as env on one service.

## Why these choices

- **One image, config via env.** Twelve-factor style: a city is just configuration,
  so the same artifact that passes canary is what ships everywhere. No per-city code.
- **Liveness ≠ readiness.** Modeling warmup (503 → 200) is what makes a health gate
  honest — you wait for *ready*, not merely *alive*, before judging a deploy.
- **`DEGRADED_MODE` as a first-class switch.** Realistic failures are "up but bad,"
  not "process down." A single flag reproduces slow + erroring so rollouts and
  monitoring can be tested deterministically (`--bad`).
- **Rolling window metrics + self-generated probe load.** p95/error-rate over the last
  200 requests is cheap, needs no external store, and the canary supplies its own
  traffic so the gate never reads a cold, empty metric.
- **Compose for deploy, a thin script only for the gate.** Deploy/status/teardown are
  solved by Compose; the only thing worth scripting is the *decision* (gate + rollback),
  which is where the SRE value is. Less bespoke tooling to trust.
- **Blast radius = one city, override via `mktemp` + `--no-deps`.** The safest rollout
  is one that can only affect a single instance and leaves the committed compose file
  untouched, so there is nothing to clean up if it fails.
