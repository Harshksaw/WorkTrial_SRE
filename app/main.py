import asyncio
import os
import random
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Deque, Dict, List

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except ValueError:
        return default


# Location-specific behavior is intentionally driven by environment variables so the
# same image can represent many independent POPs/locations.
LOCATION = os.getenv("LOCATION", "local")
VERSION = os.getenv("VERSION", "v1")
BASE_LATENCY_MS = _env_int("BASE_LATENCY_MS", 100)
TAIL_LATENCY_MS = _env_int("TAIL_LATENCY_MS", 80)
TAIL_PROBABILITY = _env_float("TAIL_PROBABILITY", 0.10)
ERROR_RATE = _env_float("ERROR_RATE", 0.0)
DEGRADED_MODE = _env_bool("DEGRADED_MODE", False)
WARMUP_SECONDS = _env_float("WARMUP_SECONDS", 2.0)
HEALTH_STATE = os.getenv("HEALTH_STATE", "ok").strip().lower()  # ok | degraded | failing
GPU_UTILIZATION = _env_float("GPU_UTILIZATION", 0.45)
GPU_MEMORY_PERCENT = _env_float("GPU_MEMORY_PERCENT", 0.55)
QUEUE_DEPTH = _env_int("QUEUE_DEPTH", 0)

READY = False
STARTED_AT = time.time()

# Rolling in-process metrics. This keeps the assessment self-contained: no Prometheus
# server or database is required for useful local observability.
LATENCIES_MS: Deque[float] = deque(maxlen=200)
RECENT_REQUEST_TIMES: Deque[float] = deque(maxlen=500)
REQUEST_COUNT = 0
ERROR_COUNT = 0
IN_FLIGHT = 0
METRIC_LOCK = asyncio.Lock()


class InferRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    max_tokens: int = Field(default=16, ge=1, le=128)


class InferResponse(BaseModel):
    completion: str
    location: str
    version: str
    simulated_latency_ms: float
    tokens: List[str]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global READY
    READY = False
    asyncio.create_task(_warmup())
    yield


app = FastAPI(
    title="PolarGrid Mock Inference Service",
    description="Local simulation of a location-aware inference endpoint.",
    version=VERSION,
    lifespan=lifespan,
)


async def _warmup() -> None:
    global READY
    await asyncio.sleep(max(WARMUP_SECONDS, 0.0))
    READY = True


def _percentile(values: Deque[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((pct / 100.0) * (len(ordered) - 1))
    return float(ordered[index])


def _effective_behavior() -> Dict[str, float]:
    """Return the active behavior after applying degraded/failing overrides."""
    error_rate = ERROR_RATE
    tail_latency_ms = TAIL_LATENCY_MS
    tail_probability = TAIL_PROBABILITY
    gpu_utilization = GPU_UTILIZATION
    gpu_memory = GPU_MEMORY_PERCENT
    queue_depth = QUEUE_DEPTH

    if DEGRADED_MODE or HEALTH_STATE == "degraded":
        error_rate = max(error_rate, 0.25)
        tail_latency_ms = max(tail_latency_ms, BASE_LATENCY_MS * 2)
        tail_probability = max(tail_probability, 0.70)
        gpu_utilization = max(gpu_utilization, 0.92)
        gpu_memory = max(gpu_memory, 0.88)
        queue_depth = max(queue_depth, 25)

    if HEALTH_STATE == "failing":
        error_rate = max(error_rate, 0.60)
        tail_latency_ms = max(tail_latency_ms, BASE_LATENCY_MS * 4)
        tail_probability = max(tail_probability, 0.90)
        gpu_utilization = max(gpu_utilization, 0.98)
        gpu_memory = max(gpu_memory, 0.95)
        queue_depth = max(queue_depth, 100)

    return {
        "error_rate": min(max(error_rate, 0.0), 1.0),
        "tail_latency_ms": max(float(tail_latency_ms), 0.0),
        "tail_probability": min(max(tail_probability, 0.0), 1.0),
        "gpu_utilization": min(max(gpu_utilization, 0.0), 1.0),
        "gpu_memory_percent": min(max(gpu_memory, 0.0), 1.0),
        "queue_depth": float(queue_depth),
    }


def _recent_throughput_rps(now: float) -> float:
    cutoff = now - 60.0
    recent = [ts for ts in RECENT_REQUEST_TIMES if ts >= cutoff]
    return round(len(recent) / 60.0, 2)


def _metrics_snapshot() -> Dict[str, object]:
    behavior = _effective_behavior()
    now = time.time()
    error_rate = ERROR_COUNT / REQUEST_COUNT if REQUEST_COUNT else 0.0
    p95 = _percentile(LATENCIES_MS, 95)
    overloaded = (
        behavior["gpu_utilization"] >= 0.90
        or behavior["gpu_memory_percent"] >= 0.90
        or behavior["queue_depth"] >= 50
        or IN_FLIGHT >= 25
    )
    degraded = DEGRADED_MODE or HEALTH_STATE in {"degraded", "failing"} or error_rate > 0.05 or p95 > 750

    return {
        "location": LOCATION,
        "version": VERSION,
        "uptime_seconds": round(now - STARTED_AT, 1),
        "ready": READY,
        "health_state": HEALTH_STATE,
        "degraded_mode": DEGRADED_MODE,
        "degraded": degraded,
        "request_count": REQUEST_COUNT,
        "error_count": ERROR_COUNT,
        "error_rate": round(error_rate, 4),
        "throughput_rps_60s": _recent_throughput_rps(now),
        "in_flight": IN_FLIGHT,
        "queue_depth": int(behavior["queue_depth"]),
        "p50_ms": round(_percentile(LATENCIES_MS, 50), 1),
        "p95_ms": round(p95, 1),
        "p99_ms": round(_percentile(LATENCIES_MS, 99), 1),
        "base_latency_ms": BASE_LATENCY_MS,
        "tail_latency_ms": int(behavior["tail_latency_ms"]),
        "configured_error_rate": round(float(behavior["error_rate"]), 4),
        "gpu_utilization": round(float(behavior["gpu_utilization"]), 2),
        "gpu_memory_percent": round(float(behavior["gpu_memory_percent"]), 2),
        "overloaded": overloaded,
    }


@app.get("/health")
async def health():
    status_code = 503 if HEALTH_STATE == "failing" else 200
    payload = {
        "status": "ok" if status_code == 200 else "failing",
        "location": LOCATION,
        "version": VERSION,
        "health_state": HEALTH_STATE,
        "degraded_mode": DEGRADED_MODE,
    }
    return JSONResponse(status_code=status_code, content=payload)


@app.get("/ready")
async def ready():
    is_ready = READY and HEALTH_STATE != "failing"
    status_code = 200 if is_ready else 503
    reason = "ready" if is_ready else ("warming" if not READY else HEALTH_STATE)
    return JSONResponse(
        status_code=status_code,
        content={"ready": is_ready, "reason": reason, "location": LOCATION, "version": VERSION},
    )


@app.get("/metrics")
async def metrics():
    return _metrics_snapshot()


@app.get("/metrics/prometheus", response_class=PlainTextResponse)
async def prometheus_metrics():
    m = _metrics_snapshot()
    lines = [
        f'pg_requests_total{{location="{LOCATION}",version="{VERSION}"}} {m["request_count"]}',
        f'pg_errors_total{{location="{LOCATION}",version="{VERSION}"}} {m["error_count"]}',
        f'pg_error_rate{{location="{LOCATION}",version="{VERSION}"}} {m["error_rate"]}',
        f'pg_latency_p95_ms{{location="{LOCATION}",version="{VERSION}"}} {m["p95_ms"]}',
        f'pg_gpu_utilization{{location="{LOCATION}",version="{VERSION}"}} {m["gpu_utilization"]}',
        f'pg_queue_depth{{location="{LOCATION}",version="{VERSION}"}} {m["queue_depth"]}',
        f'pg_overloaded{{location="{LOCATION}",version="{VERSION}"}} {1 if m["overloaded"] else 0}',
    ]
    return "\n".join(lines) + "\n"


@app.post("/infer", response_model=InferResponse)
async def infer(request: InferRequest):
    global REQUEST_COUNT, ERROR_COUNT, IN_FLIGHT

    if not READY or HEALTH_STATE == "failing":
        async with METRIC_LOCK:
            REQUEST_COUNT += 1
            ERROR_COUNT += 1
            RECENT_REQUEST_TIMES.append(time.time())
        return JSONResponse(
            status_code=503,
            content={"error": "location not ready", "location": LOCATION, "version": VERSION},
        )

    behavior = _effective_behavior()
    latency_ms = float(BASE_LATENCY_MS)
    if random.random() < behavior["tail_probability"]:
        latency_ms += float(behavior["tail_latency_ms"])

    start = time.monotonic()
    IN_FLIGHT += 1
    await asyncio.sleep(latency_ms / 1000.0)
    observed_latency_ms = (time.monotonic() - start) * 1000.0
    IN_FLIGHT -= 1

    failed = random.random() < behavior["error_rate"]
    async with METRIC_LOCK:
        REQUEST_COUNT += 1
        if failed:
            ERROR_COUNT += 1
        LATENCIES_MS.append(observed_latency_ms)
        RECENT_REQUEST_TIMES.append(time.time())

    if failed:
        return JSONResponse(
            status_code=500,
            content={
                "error": "simulated inference failure",
                "location": LOCATION,
                "version": VERSION,
                "simulated_latency_ms": round(observed_latency_ms, 1),
            },
        )

    # Deterministic fake completion: enough to look inference-like without a model.
    words = request.prompt.strip().split()
    generated = list(reversed(words))[: request.max_tokens] or ["ok"]
    return {
        "completion": " ".join(generated),
        "location": LOCATION,
        "version": VERSION,
        "simulated_latency_ms": round(observed_latency_ms, 1),
        "tokens": generated,
    }
