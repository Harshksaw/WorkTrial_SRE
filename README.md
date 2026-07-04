# WorkTrial_SRE — PolarGrid Multi-Location Deployment Simulation

A local SRE work-trial implementation for simulating a distributed AI inference fleet across five locations: **vancouver**, **toronto**, **london**, **frankfurt**, and **singapore**.

The project runs completely on a laptop with Docker Compose. It creates one tiny FastAPI inference-like service and deploys it as five independently configured location instances. The included `ops` CLI gives an operator repeatable workflows for setup, deployment, fleet status, traffic probes, failure injection, canary rollout, rollback, and teardown.

## What this demonstrates

- Consistent deployment of one service image across multiple locations.
- Location-specific configuration for latency, version, failure mode, error rate, and simulated GPU/resource metrics.
- Operational visibility across health, readiness, latency, error rate, throughput, version, queue depth, and simulated GPU utilization.
- Safe rollout using a one-location canary with a health gate before wider promotion.
- Failure isolation by degrading one location without touching the rest of the fleet.
- Rollback of one problematic location to a previous known-good version.

## Architecture at a glance

```text
operator
  |
  | bash ops ...
  v
Docker Compose local fleet
  |
  +-- vancouver :8001
  +-- toronto   :8002
  +-- london    :8003
  +-- frankfurt :8004
  +-- singapore :8005

same FastAPI image, independent env config per location
```

Each location exposes:

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness and deployed version. |
| `GET /ready` | Readiness after warmup; returns `503` while warming or failing. |
| `GET /metrics` | JSON operational metrics used by `bash ops status`. |
| `GET /metrics/prometheus` | Prometheus-style text metrics for realism. |
| `POST /infer` | Deterministic fake inference with simulated latency and errors. |

## Repository layout

```text
.
├── app/main.py              # FastAPI mock inference service
├── docs/architecture.md     # Design and implementation notes
├── docs/operator-guide.md   # Step-by-step runbook
├── docs/tradeoffs.md        # Timebox tradeoffs and production changes
├── Dockerfile
├── docker-compose.yml       # Five local location instances
├── ops                      # Main operator CLI
├── ops-canary.sh            # Compatibility wrapper for canary flow
├── pyproject.toml
├── uv.lock
└── README.md
```

## Prerequisites

Required:

- Docker with Docker Compose v2
- `bash`
- `curl`
- `python3`

Optional: `uv`, only if running the FastAPI service directly outside Docker.

Check Docker Compose:

```bash
docker compose version
```

## Quick start

```bash
# 1. Build the service image
bash ops setup

# 2. Deploy all five locations on ports 8001-8005
bash ops deploy all v1

# 3. Generate probe traffic and show fleet health
bash ops status --probe

# 4. Simulate one degraded location
bash ops degrade london latency

# 5. Inspect which location is degraded / worst latency / erroring
bash ops status

# 6. Recover that location
bash ops recover london

# 7. Roll out a new version safely
bash ops rollout v2

# 8. Demonstrate a bad rollout that is stopped at canary
bash ops rollout v3 --bad

# 9. Tear everything down
bash ops teardown
```

## Operator CLI

```bash
bash ops setup
bash ops deploy [all|LOCATION] [VERSION]
bash ops status [--probe]
bash ops load [LOCATION|all] [REQUESTS]
bash ops degrade LOCATION [latency|errors|overload|failing]
bash ops recover LOCATION
bash ops canary VERSION [LOCATION] [--bad]
bash ops rollout VERSION [--bad]
bash ops rollback LOCATION [VERSION]
bash ops teardown
```

Location names:

```text
vancouver toronto london frankfurt singapore
```

Port map:

| Location | Port |
|---|---:|
| vancouver | 8001 |
| toronto | 8002 |
| london | 8003 |
| frankfurt | 8004 |
| singapore | 8005 |

## Inspect one location manually

```bash
curl -s localhost:8001/health | python3 -m json.tool
curl -s localhost:8001/ready | python3 -m json.tool
curl -s localhost:8001/metrics | python3 -m json.tool
curl -s -X POST localhost:8001/infer \
  -H 'content-type: application/json' \
  -d '{"prompt":"hello from vancouver","max_tokens":8}' | python3 -m json.tool
```

## Safe rollout workflow

A normal rollout uses **vancouver** as the canary first:

```bash
bash ops rollout v2
```

The workflow is executable and risk-limited:

1. Deploy `v2` to one location only.
2. Wait for `/ready`.
3. Send probe inference traffic.
4. Evaluate the gate:
   - health must be `200`
   - readiness must be `200`
   - error rate must be `<= 5%`
   - p95 latency must be `<= 750ms`
   - location must not be overloaded
   - location must not report degraded state
5. Promote to the remaining locations one at a time only if the gate passes.
6. Stop and roll back the current location if any gate fails.

Bad release demo:

```bash
bash ops rollout v3 --bad
```

That command deliberately makes the canary degraded. The gate fails, the canary is rolled back, and no other location receives the bad version.

## Failure detection scenario

Make London slow/erroring while the other cities stay healthy:

```bash
bash ops degrade london latency
bash ops status
```

The status output makes the failure operationally obvious by showing state, version, error rate, p95 latency, simulated GPU, memory, queue depth, and a summary:

```text
Fleet summary
  worst_latency: london p95=...
  degraded:      london
  erroring:      london
  overloaded:    ...
```

Recover London:

```bash
bash ops recover london
```

## Documentation

- [Architecture](docs/architecture.md)
- [Operator Guide](docs/operator-guide.md)
- [Tradeoffs](docs/tradeoffs.md)
