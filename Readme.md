# WorkTrial_SRE — Fleet Simulation

> SRE fleet simulation: a fake inference service deployed as 5 simulated cities, driven by an `ops` CLI with canary rollouts, health gating, and live monitoring.

This repo is an SRE playground. A single fake inference service is deployed as five independent "city" instances via Docker Compose. An `ops` bash CLI drives the fleet — deploying, monitoring, rolling out new versions behind a health gate, injecting failures, and tearing everything down.

> **Status: setup phase.** This README captures the build plan. No application code, compose file, or `ops` script exists yet — those are built in later tasks.

---

## Architecture (planned)

```
        ┌─────────────────────────────────────────────┐
        │                 ops (bash CLI)              │
        │  deploy · status · rollout · rollback ·     │
        │        inject-failure · teardown            │
        └───────────────────┬─────────────────────────┘
                            │  docker compose
                            ▼
   ┌──────────┬──────────┬──────────┬──────────┬──────────┐
   │  city-1  │  city-2  │  city-3  │  city-4  │  city-5  │
   │  :8001   │  :8002   │  :8003   │  :8004   │  :8005   │
   └──────────┴──────────┴──────────┴──────────┴──────────┘
        each = FastAPI inference service (env-configured)
        exposes /health · /ready · /metrics · /infer
                            ▲
                            │  polls /health + /metrics
                            │
                    monitor (status table)
```

- **Service**: one FastAPI app, behavior fully driven by env vars.
- **Fleet**: five instances (cities) on ports 8001–8005, same image, different config.
- **Control plane**: the `ops` script + a polling monitor.

---

## Build Plan

### 1. Fake inference service (FastAPI)
A single FastAPI app whose behavior is entirely controlled by environment variables. Endpoints:

| Endpoint   | Purpose                                                        |
|------------|---------------------------------------------------------------|
| `/health`  | Liveness — is the process up?                                  |
| `/ready`   | Readiness — is it ready to serve traffic?                      |
| `/metrics` | Prometheus-style counters + latency histograms                |
| `/infer`   | Simulated inference call (applies latency / error behavior)   |

**Env-var configuration:**

| Variable        | Meaning                                                      |
|-----------------|-------------------------------------------------------------|
| `LOCATION`      | City / instance identifier                                  |
| `VERSION`       | Deployed service version (used by canary rollout)           |
| `BASE_LATENCY`  | Baseline response latency                                   |
| `TAIL_LATENCY`  | Tail (p99-ish) latency for a slice of requests              |
| `ERROR_RATE`    | Fraction of requests that return errors                     |
| `DEGRADED`      | Toggle degraded-but-alive behavior                          |
| `MODE`          | Operating mode (e.g. normal / degraded / failing)           |

### 2. Five simulated cities
A `docker-compose.yml` defining five instances of the same image, each mapped to a port in the **8001–8005** range and given a distinct `LOCATION` and config via env.

### 3. `ops` bash script
A single CLI entrypoint with subcommands:

| Subcommand        | Intent                                                          |
|-------------------|----------------------------------------------------------------|
| `deploy`          | Bring the fleet up via docker compose                          |
| `status`          | Show the live status table across all cities                  |
| `rollout`         | Canary-roll a new `VERSION` across the fleet behind a gate    |
| `rollback`        | Revert to the previous known-good version                     |
| `inject-failure`  | Force a city into a degraded / failing mode for testing       |
| `teardown`        | Stop and remove the fleet                                     |

### 4. Monitoring
A status table that polls every city's `/health` and `/metrics` and renders a live fleet view — per-city health, version, latency, and error rate at a glance.

### 5. Canary rollout with health gate
Roll a new `VERSION` to **one** city first, poll its `/health` and `/metrics`, and promote to the rest of the fleet **only if the health gate passes**. If the gate fails, auto-rollback the canary.

### 6. Docs
A `docs/` directory covering:
- **Architecture** — how the pieces fit together.
- **Operator guide** — how to run each `ops` subcommand and read the monitor.
- **Tradeoffs** — design decisions and their compromises.

---

## Planned layout

> _Planned — not yet created._

```
WorkTrial_SRE/
├── app/                  # FastAPI inference service
│   ├── main.py
│   └── ...
├── Dockerfile            # image for the service
├── docker-compose.yml    # 5 cities on ports 8001–8005
├── ops                   # bash CLI (deploy/status/rollout/…)
├── docs/
│   ├── architecture.md
│   ├── operator-guide.md
│   └── tradeoffs.md
├── README.md
└── Notes.md              # decision log
```

---

## Status

- [ ] 1. Fake inference service (FastAPI)
- [ ] 2. Five simulated cities (docker compose, 8001–8005)
- [ ] 3. `ops` bash script (deploy/status/rollout/rollback/inject-failure/teardown)
- [ ] 4. Monitoring status table
- [ ] 5. Canary rollout with health gate
- [ ] 6. Docs (architecture / operator guide / tradeoffs)
