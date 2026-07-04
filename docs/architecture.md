# Architecture

## Goal

This project simulates a globally distributed AI inference deployment environment on a local machine. The focus is operational behavior: consistent deploys, location identity, version visibility, health/readiness, performance signals, failure isolation, safe rollout, and rollback.

## System design

```text
operator
  |
  | bash ops <command>
  v
Docker Compose local fleet
  |
  +-- vancouver :8001
  +-- toronto   :8002
  +-- london    :8003
  +-- frankfurt :8004
  +-- singapore :8005

same FastAPI image, independent env configuration per location
```

There is one application artifact: `worktrial-sre:latest`. Docker Compose runs that same image five times with different environment variables and host ports. This models a production pattern where the same release artifact is promoted across locations while each location keeps its own operational identity and runtime configuration.

## Tiny inference service

The service lives in `app/main.py` and exposes:

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Liveness. Returns location, version, health state, and degraded flag. |
| `/ready` | GET | Readiness. Returns `503` during warmup or if the location is failing. |
| `/metrics` | GET | JSON metrics consumed by the operator CLI. |
| `/metrics/prometheus` | GET | Prometheus-style text metrics for realism. |
| `/infer` | POST | Fake deterministic inference with simulated latency and failures. |

The inference response reverses words from the prompt. That is intentionally simple: the important part is the operational request path, not the completion quality.

## Location simulation

Each location is a Compose service. It has its own container instance, host port, `LOCATION`, latency profile, resource profile, version, and degradation/failure behavior.

| Location | Port | Normal base latency |
|---|---:|---:|
| vancouver | 8001 | 120 ms |
| toronto | 8002 | 160 ms |
| london | 8003 | 220 ms |
| frankfurt | 8004 | 200 ms |
| singapore | 8005 | 300 ms |

Important environment variables:

| Variable | Meaning |
|---|---|
| `LOCATION` | Operational identity of the location. |
| `VERSION` | Release version currently running at that location. |
| `BASE_LATENCY_MS` | Normal inference latency floor. |
| `TAIL_LATENCY_MS` | Extra latency added to tail requests. |
| `TAIL_PROBABILITY` | Probability that a request hits the tail. |
| `ERROR_RATE` | Simulated inference failure probability. |
| `DEGRADED_MODE` | Makes a location alive but slow/erroring/overloaded. |
| `HEALTH_STATE` | `ok`, `degraded`, or `failing`. |
| `GPU_UTILIZATION` | Simulated GPU utilization. |
| `GPU_MEMORY_PERCENT` | Simulated GPU memory pressure. |
| `QUEUE_DEPTH` | Simulated request queue depth. |

## Deployment automation

`bash ops` is the local operator interface. It wraps Docker Compose and HTTP probes.

| Command | Purpose |
|---|---|
| `bash ops setup` | Build the service image. |
| `bash ops deploy all v1` | Deploy all locations on version `v1`. |
| `bash ops deploy london v2` | Deploy one location to a target version. |
| `bash ops status --probe` | Generate probe traffic and print fleet status. |
| `bash ops degrade london latency` | Recreate one location in degraded mode. |
| `bash ops recover london` | Recreate one location in healthy mode. |
| `bash ops canary v2 vancouver` | Deploy and gate one location. |
| `bash ops rollout v2` | Canary first, then promote sequentially. |
| `bash ops rollback london v1` | Roll one location back. |
| `bash ops teardown` | Stop and remove the local fleet. |

Single-location deploys are implemented through temporary Compose override files plus `up -d --no-deps`. This keeps the committed Compose file stable while allowing one location to be recreated with a new version or degradation state.

## Monitoring model

`ops status` calls `/health`, `/ready`, and `/metrics` for every port. It renders a fleet table with state, version, readiness, requests, error rate, p95 latency, RPS, GPU, memory, and queue depth. It then prints an operational summary: worst latency, degraded locations, erroring locations, and overloaded locations.

The service keeps in-process rolling metrics: last 200 request latencies, total request count, total error count, recent request timestamps for 60-second throughput, current in-flight request count, and simulated resource metrics. This avoids external dependencies while still giving useful signals.

## Rollout and rollback

The safe rollout path is intentionally conservative:

```text
new version -> deploy to vancouver only -> wait for /ready -> probe /infer -> evaluate gate
                                                             | pass: promote one at a time
                                                             | fail: rollback canary and stop
```

The gate requires:

- `/health` returns `200`,
- `/ready` returns `200`,
- error rate is at most `5%`,
- p95 latency is at most `750ms`,
- location is not overloaded,
- location does not report degraded state.

Rollback uses the same deployment mechanism as rollout. The `ops` CLI records each location's previous version in `.ops-state/<location>.previous` before a location deploy, so `bash ops rollback <location>` can revert to the last known version. A version can also be supplied explicitly.

## Failure detection

`bash ops degrade LOCATION MODE` recreates exactly one location with degraded configuration. For example:

```bash
bash ops degrade london latency
bash ops status
```

The degraded location remains up, which is realistic: many production incidents are not hard crashes. The service is still reachable but has elevated tail latency, higher error rate, higher simulated GPU pressure, and queue buildup. The status summary makes the location actionable without needing to inspect logs.

## Why this design

- Docker Compose keeps the solution locally runnable and easy to review.
- One image plus environment config models real release promotion better than per-location code changes.
- Readiness separate from health prevents rollout logic from promoting a process that has started but is not ready to serve.
- In-process metrics avoid extra infrastructure while preserving operational clarity.
- Canary-first rollout minimizes blast radius to one location.
- Temporary Compose overrides make single-location deploys simple and avoid mutating the base configuration.
