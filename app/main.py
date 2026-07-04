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
ERROR_RATE= float(os.getenv("ERROR_RATE", "0.0"))
TAIL_LATENCY_MS = int(os.getenv("TAIL_LATENCY_MS", "0"))
DEGRADED_MODE= os.getenv("DEGRADED_MODE", "false").lower() == "true"

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
    global REQUEST_COUNT, ERROR_COUNT
    start = time.monotonic()
    # Simulate model inference time.

    effective_error_rate = ERROR_RATE
    effective_tail_ms = TAIL_LATENCY_MS
    tail_probability = 0.1
    if DEGRADED_MODE:
        effective_error_rate = max (effective_error_rate, 0.25)

        effective_tail_ms = max(effective_tail_ms,BASE_LATENCY_MS ) 
        tail_probability = 0.7

    latency_s = BASE_LATENCY_MS /1000

    if effective_tail_ms and random.random() < tail_probability:
        latency_s += effective_tail_ms/ 1000
        
    time.sleep(latency_s)
    latency_ms = (time.monotonic() - start) * 1000
    if random.random() < ERROR_RATE:
        ERROR_COUNT +=1
        return JSONResponse(status_code=500, content={"error": "simulated error"})

    REQUEST_COUNT += 1
    LATENCIES_MS.append(latency_ms)
     
    if random.random() < effective_error_rate:
        ERROR_COUNT +=1
        return JSONResponse(status_code=500, content={"error": "inference failed", "location": LOCATION})
    


    return {"completion": f"echo: {request.prompt}", "location": LOCATION}
