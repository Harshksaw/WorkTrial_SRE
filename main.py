import asyncio
import os
import random
import time
from collections import deque

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Behavior is driven entirely by environment variables.
LOCATION = os.getenv("LOCATION", "local")
VERSION = os.getenv("VERSION", "v1")
BASE_LATENCY_MS = int(os.getenv("BASE_LATENCY_MS", "100"))

app = FastAPI()

# Readiness is tracked separately from liveness: the process is alive
# immediately, but only becomes ready after a simulated warmup.
READY = False

# Metrics state, updated on every /infer call.
LATENCIES_MS = deque(maxlen=200)  # last 200 request latencies
REQUEST_COUNT = 0
ERROR_COUNT = 0


class InferRequest(BaseModel):
    prompt: str


async def _warmup():
    # Simulate model load / warmup, then flip to ready.
    global READY
    await asyncio.sleep(2)
    READY = True


@app.on_event("startup")
async def on_startup():
    # Run warmup in the background so the server serves 503s while warming.
    asyncio.create_task(_warmup())


def _percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    k = int(round((pct / 100) * (len(ordered) - 1)))
    return ordered[k]


@app.get("/health")
def health():
    return {"status": "ok", "location": LOCATION, "version": VERSION}


@app.get("/ready")
def ready():
    if not READY:
        return JSONResponse(status_code=503, content={"ready": False})
    return {"ready": True, "location": LOCATION}


@app.get("/metrics")
def metrics():
    error_rate = ERROR_COUNT / REQUEST_COUNT if REQUEST_COUNT else 0.0
    return {
        "location": LOCATION,
        "version": VERSION,
        "request_count": REQUEST_COUNT,
        "error_rate": error_rate,
        "p50_ms": _percentile(LATENCIES_MS, 50),
        "p95_ms": _percentile(LATENCIES_MS, 95),
        "p99_ms": _percentile(LATENCIES_MS, 99),
        "gpu_utilization": round(random.uniform(0.3, 0.95), 2),
    }


@app.post("/infer")
def infer(request: InferRequest):
    global REQUEST_COUNT
    start = time.monotonic()
    # Simulate model inference time.
    time.sleep(BASE_LATENCY_MS / 1000)
    latency_ms = (time.monotonic() - start) * 1000

    REQUEST_COUNT += 1
    LATENCIES_MS.append(latency_ms)

    return {"completion": f"echo: {request.prompt}", "location": LOCATION}
