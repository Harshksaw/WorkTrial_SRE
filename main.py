import os
import time

from fastapi import FastAPI
from pydantic import BaseModel

# Behavior is driven entirely by environment variables.
LOCATION = os.getenv("LOCATION", "local")
VERSION = os.getenv("VERSION", "v1")
BASE_LATENCY_MS = int(os.getenv("BASE_LATENCY_MS", "100"))

app = FastAPI()


class InferRequest(BaseModel):
    prompt: str


@app.get("/health")
def health():
    return {"status": "ok", "location": LOCATION, "version": VERSION}


@app.post("/infer")
def infer(request: InferRequest):
    # Simulate model inference time.
    time.sleep(BASE_LATENCY_MS / 1000)
    return {"completion": f"echo: {request.prompt}", "location": LOCATION}
