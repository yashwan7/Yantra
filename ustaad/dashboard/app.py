"""Dashboard FastAPI app — full implementation in Phase 5."""
# Phase 0 stub
from fastapi import FastAPI

app = FastAPI(title="Ustaad Dashboard", version="0.1.0")


@app.get("/")
async def root():
    return {"status": "Phase 0 stub — full dashboard in Phase 5"}


@app.get("/api/state")
async def get_state():
    return {"phase": 0, "note": "stub"}
