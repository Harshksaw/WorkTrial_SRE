# Tradeoffs

## What this solution optimizes for

This implementation optimizes for local runnability, operational clarity, and a reviewer-friendly workflow inside a 3-4 hour work-trial timebox.

The main objective is to make the system easy to understand and operate:

- one command to build,
- one command to deploy,
- one command to view fleet state,
- one command to inject a failure,
- one command to roll out safely,
- one command to roll back,
- one command to tear down.

## Shortcuts taken for the timebox

### Docker Compose instead of Kubernetes

Docker Compose is not a global production orchestrator. It is used here because the requirement is local simulation with no cloud account or specialized hardware. Compose is enough to model independent location instances, versioned deploys, health checks, and single-location recreation.

In production, I would expect Kubernetes, Nomad, ECS, or an internal scheduler with explicit rollout strategies and traffic management.

### In-process metrics instead of a metrics backend

Metrics are kept in memory and reset when a container restarts. This is intentional for a self-contained simulation.

In production, metrics would be scraped into Prometheus, Mimir, Datadog, CloudWatch, or another time-series backend. Alerts would be based on windows, burn rates, service-level objectives, and routing impact.

### Simulated GPU/resource metrics

There is no real GPU. GPU utilization, memory pressure, and queue depth are simulated through environment variables and degradation modes.

In production, these would come from NVIDIA DCGM, node exporters, model server metrics, queueing systems, and request router telemetry.

### Local port mapping instead of real regions/POPs

Locations are represented by host ports. This gives each location independent identity without requiring machines in different regions.

In production, each location would map to a real cluster, region, POP, or edge site, and routing decisions would consider network RTT, capacity, model availability, and user geography.

### Bash CLI instead of a full control plane

The `ops` script is deliberately thin. It exposes the operator workflow without introducing a large framework.

In production, deployment state, approvals, progressive delivery, audit logs, and rollback history would live in a deployment platform such as Argo CD, Spinnaker, Flux, GitHub Actions, Buildkite, or an internal release system.

### Simple health gate

The gate uses straightforward thresholds:

- health is `200`,
- readiness is `200`,
- error rate <= `5%`,
- p95 latency <= `750ms`,
- not overloaded,
- not degraded.

In production, I would use service-level indicators and compare canary vs. baseline with enough traffic volume. A real rollout gate would likely include minimum request count, latency regression percentage vs. control, 5xx rate, timeout rate, queue depth, GPU saturation, model load failures, pod/container restarts, router-level success rate, and automatic abort windows.

## What would change in real production

### Deployment

- Use immutable image tags instead of symbolic versions like `v1`/`v2`.
- Store desired state in Git.
- Use progressive rollout tooling.
- Use per-location deployment policies.
- Track release provenance, commit SHA, image digest, and config version.

### Monitoring and alerting

- Export real Prometheus/OpenTelemetry metrics.
- Add distributed tracing for request path and model latency.
- Define SLOs for availability, time to first token, total latency, and error rate.
- Alert on burn rate and regional impact rather than raw threshold breaches only.
- Build dashboards for location comparison, version comparison, and routing decisions.

### Routing and isolation

- Add a traffic router in front of locations.
- Drain traffic before rollout or rollback.
- Route around degraded locations automatically.
- Use weighted canaries and regional failover.
- Keep per-location circuit breakers.

### Reliability

- Add persistent logs.
- Add restart/backoff visibility.
- Add chaos/failure scenarios beyond latency/errors, such as partial model load, bad config, resource exhaustion, network timeout, and dependency failure.
- Add automated tests for the operator workflow.

### Security and configuration

- Avoid ad hoc environment overrides for sensitive settings.
- Use a secrets manager.
- Validate configuration before deployment.
- Enforce least-privilege operator permissions.

## Why the current level of complexity is appropriate

The assessment asks for a tiny local simulation, repeatable deployment automation, performance visibility, safe rollout, rollback, failure detection, and strong documentation. This solution covers those requirements without adding infrastructure that would make the reviewer spend more time understanding tooling than evaluating engineering judgment.
