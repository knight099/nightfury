import os
import sys

from fastapi import FastAPI

sys.path.insert(0, os.path.dirname(__file__))

from config import config

app = FastAPI(title="Nightwatch Worker", docs_url=None, redoc_url=None)


@app.get("/healthz")
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "nightwatch-worker",
        "backend_url": config.backend_url,
        "worker_id": config.worker_id,
        "mjpeg_server_enabled": config.mjpeg_server_enabled,
        "stream_token_secret_set": bool(config.stream_token_secret),
    }

