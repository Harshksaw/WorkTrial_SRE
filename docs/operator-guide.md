# Operator Guide

This is the runbook for setting up, deploying, monitoring, breaking, rolling out, rolling back, and cleaning up the local multi-location fleet.

## Prerequisites

Required tools:

```bash
docker compose version
bash --version
python3 --version
curl --version
```

No cloud account, GPU, Kubernetes cluster, or external monitoring system is required.

## Location map

| Location | URL |
|---|---|
| vancouver | `http://localhost:8001` |
| toronto | `http://localhost:8002` |
| london | `http://localhost:8003` |
| frankfurt | `http://localhost:8004` |
| singapore | `http://localhost:8005` |

Every location exposes `/health`, `/ready`, `/metrics`, `/metrics/prometheus`, and `/infer`.

## 1. Set up the environment

From the repository root:

```bash
bash ops setup
```

This builds the `worktrial-sre:latest` image from the local `Dockerfile`.

## 2. Deploy the full fleet

```bash
bash ops deploy all v1
```

This starts all five locations on version `v1`.

Check container state:

```bash
docker compose ps
```

## 3. Check status

Use the built-in fleet view:

```bash
bash ops status
```

On a fresh deploy there may be little latency/error data because no inference traffic has happened yet. To generate probe traffic and then print status:

```bash
bash ops status --probe
```

The status table answers the core operator questions: which locations are healthy, which are degraded, which has the worst p95 latency, which are erroring, whether any appear overloaded, and what version is running where.

| Column | Meaning |
|---|---|
| `CITY` | Location identity. |
| `STATE` | `HEALTHY`, `DEGRADED`, `OVERLOADED`, `UNREADY`, or `DOWN`. |
| `VER` | Deployed version from `/health`. |
| `READY` | Whether `/ready` is passing. |
| `REQ` | Total inference requests observed by that process. |
| `ERR` | Error rate. |
| `P95` | Rolling p95 latency. |
| `RPS` | Recent 60-second throughput. |
| `GPU` | Simulated GPU utilization. |
| `MEM` | Simulated GPU memory pressure. |
| `QUEUE` | Simulated queue depth. |

## 4. Inspect one location manually

```bash
curl -s localhost:8001/health | python3 -m json.tool
curl -s localhost:8001/ready | python3 -m json.tool
curl -s localhost:8001/metrics | python3 -m json.tool
```

Send one inference request:

```bash
curl -s -X POST localhost:8001/infer \
  -H 'content-type: application/json' \
  -d '{"prompt":"hello from vancouver","max_tokens":8}' | python3 -m json.tool
```

Generate load:

```bash
bash ops load all 50
bash ops status
```

## 5. Deploy one location

Deploy only Toronto to `v2`:

```bash
bash ops deploy toronto v2
bash ops status --probe
```

Only Toronto should report `v2`; the other locations should remain on their previous versions.

## 6. Simulate a degraded location

Latency degradation:

```bash
bash ops degrade london latency
```

Error-heavy degradation:

```bash
bash ops degrade london errors
```

Overload-like degradation:

```bash
bash ops degrade london overload
```

Failing readiness/health:

```bash
bash ops degrade london failing
```

Then inspect:

```bash
bash ops status
```

Recover the location:

```bash
bash ops recover london
bash ops status --probe
```

## 7. Canary one location

Deploy a new version to one location and gate it before promoting wider:

```bash
bash ops canary v2 vancouver
```

The canary flow:

1. Reads the current version from `/health`.
2. Recreates only the target location with the new version.
3. Waits for `/ready`.
4. Sends probe `/infer` traffic.
5. Checks the gate.
6. Leaves the canary on the new version if it passes.
7. Rolls back that one location if it fails.

Bad canary demo:

```bash
bash ops canary v3 vancouver --bad
```

The `--bad` flag intentionally applies degraded behavior to the canary. The gate should fail and automatically roll back Vancouver to the previous version.

## 8. Roll out globally with safety gates

```bash
bash ops rollout v2
```

This performs a canary on Vancouver first, then promotes Toronto, London, Frankfurt, and Singapore one at a time. Each location must pass its gate before the next location is touched. If any location fails, rollout stops, that location is rolled back, and locations not yet touched remain unchanged.

Bad rollout demo:

```bash
bash ops rollout v3 --bad
```

The bad release is injected at the canary stage, so it should not propagate beyond Vancouver.

## 9. Roll back one location

Rollback to the automatically recorded previous version:

```bash
bash ops rollback toronto
```

Rollback to an explicit version:

```bash
bash ops rollback toronto v1
```

Confirm:

```bash
bash ops status --probe
```

## 10. Tear down

```bash
bash ops teardown
```

This stops the fleet and removes `.ops-state`.

For a deeper Docker cleanup:

```bash
docker compose down --remove-orphans --rmi local -v
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `docker compose` not found | Install Docker Desktop or Docker Engine with Compose v2. |
| Port already in use | Stop the process using ports `8001`-`8005` or change ports in `docker-compose.yml`. |
| `/ready` returns `503` right after deploy | Wait a few seconds; each instance has a warmup delay. |
| `REQ` is `0` in status | Run `bash ops status --probe` or `bash ops load all 50`. |
| A location stays degraded | Run `bash ops recover LOCATION` or `bash ops rollback LOCATION v1`. |
| Rollout stops | This is expected when a gate fails; inspect `bash ops status`, then rollback/recover the bad location. |
