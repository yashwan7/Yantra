"""
dashboard/app.py — FastAPI backend for the Ustaad industrial dashboard.

Endpoints:
  GET  /api/state
  GET  /api/timeline
  GET  /api/recalled
  GET  /api/patterns
  POST /api/sim/{scenario}
  POST /api/ui/badge
  POST /api/ui/fix
  POST /api/ui/reset
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.config import get_settings
from agent.memory import get_memory_store
from agent.models import (
    FIX_OPTIONS,
    UiEvent,
    UiEventType,
)
from agent import simulator as sim_mod
from agent.state import SharedState

logger = logging.getLogger(__name__)

# Global shared state reference (bound when started by agent.main)
_app_state: Optional[SharedState] = None


def set_shared_state(state: SharedState) -> None:
    global _app_state
    _app_state = state


def get_shared_state() -> SharedState:
    global _app_state
    if _app_state is None:
        _app_state = SharedState()
    return _app_state


app = FastAPI(title="Ustaad Industrial Agent", version="1.0.0")

# Mount static folder
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ── Request / Response Models ─────────────────────────────────────────────────

class BadgeRequest(BaseModel):
    worker: str = "W-07"


class FixRequest(BaseModel):
    fix: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = _static_dir / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>Ustaad Dashboard Static Index Not Found</h1>", status_code=404)
    return FileResponse(index_file)


@app.get("/api/state")
async def get_state() -> dict[str, Any]:
    state = get_shared_state()
    cfg = get_settings()

    reading = state.latest_reading()
    features = state.get_features()
    incident = state.get_incident()
    display = state.get_display()
    recent_readings = state.get_readings()[-20:]

    return {
        "machine_id": cfg.machine_id,
        "site": cfg.site,
        "simulator_mode": cfg.simulator,
        "hindsight_enabled": cfg.use_hindsight,
        "groq_enabled": cfg.use_groq,
        "display": {
            "screen": display.screen.value,
            "title": display.title,
            "body": display.body,
            "risk": display.risk.value,
            "worker": display.worker,
            "countdown_s": display.countdown_s,
        },
        "latest_reading": {
            "ts": reading.ts if reading else None,
            "temp_c": reading.temp_c if reading else 30.0,
            "hum": reading.hum if reading else 50.0,
            "gas_raw": reading.gas_raw if reading else 410,
            "noise": reading.noise if reading else 0,
            "ldr_raw": reading.ldr_raw if reading else 2300,
            "door_open": reading.door_open if reading else False,
            "i_ma": reading.i_ma if reading else 380.0,
            "i_base_ma": reading.i_base_ma if reading else 380.0,
            "ratio": reading.ratio if reading else 1.0,
            "relay": reading.relay if reading else "ON",
            "cutoff_event": reading.cutoff_event if reading else False,
        } if reading else {},
        "features": {
            "current_ratio": features.current_ratio if features else 1.0,
            "temp_slope_c_per_min": features.temp_slope_c_per_min if features else 0.0,
            "gas_delta": features.gas_delta if features else 0.0,
            "noise_per_min": features.noise_per_min if features else 0.0,
            "door_open": features.door_open if features else False,
            "uptime_min": features.uptime_min if features else 0.0,
            "anomaly": features.anomaly.value if features else "NONE",
            "risk": features.risk.value if features else "LOW",
        } if features else {},
        "incident": {
            "id": incident.incident_id,
            "severity": incident.severity,
            "signature": incident.signature,
            "advice": incident.advice,
            "worker_id": incident.worker_id,
            "fix_chosen": incident.fix_chosen,
            "escalation": incident.escalation,
        } if incident else None,
        "recent_readings": [
            {
                "ts": r.ts,
                "i_ma": r.i_ma or 380.0,
                "temp_c": r.temp_c,
                "ratio": r.ratio or 1.0,
            }
            for r in recent_readings
        ],
        "fix_options": FIX_OPTIONS,
    }


@app.get("/api/timeline")
async def get_timeline() -> list[dict[str, Any]]:
    state = get_shared_state()
    entries = state.get_timeline()
    return [
        {
            "kind": e.kind,
            "text": e.text,
            "ts": e.ts,
            "worked": e.worked,
        }
        for e in reversed(entries)
    ]


@app.get("/api/recalled")
async def get_recalled() -> list[dict[str, Any]]:
    state = get_shared_state()
    memories = state.get_recalled()
    return [
        {
            "id": m.id,
            "text": m.text,
            "score": m.score,
            "tags": m.tags,
        }
        for m in memories
    ]


@app.get("/api/patterns")
async def get_patterns(refresh: bool = False) -> dict[str, str]:
    state = get_shared_state()
    existing = state.get_patterns()
    if existing and not refresh:
        return {"patterns": existing}

    store = get_memory_store()
    cfg = get_settings()
    question = f"What recurring fault patterns, failure root causes, and successful repairs have occurred on {cfg.machine_id}?"
    synthesized = store.reflect(question)
    state.set_patterns(synthesized)
    return {"patterns": synthesized}


@app.post("/api/sim/{scenario}")
async def trigger_sim_scenario(scenario: str) -> dict[str, str]:
    valid_scenarios = ["stall", "precursor", "gas", "door", "heat", "fix_works", "fix_fails", "reset"]
    if scenario not in valid_scenarios:
        raise HTTPException(status_code=400, detail=f"Invalid scenario '{scenario}'. Valid: {valid_scenarios}")

    state = get_shared_state()
    if scenario == "reset":
        sim_mod.reset_simulator()
    else:
        sim_mod.set_scenario(scenario)

    state.set_scenario(scenario)
    return {"status": "ok", "scenario": scenario}


@app.post("/api/ui/badge")
async def post_ui_badge(req: BadgeRequest) -> dict[str, str]:
    state = get_shared_state()
    state.ui_event_queue.put(UiEvent(type=UiEventType.BADGE, worker=req.worker))
    return {"status": "ok", "worker": req.worker}


@app.post("/api/ui/fix")
async def post_ui_fix(req: FixRequest) -> dict[str, str]:
    if req.fix not in FIX_OPTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid fix option '{req.fix}'. Valid: {FIX_OPTIONS}")
    state = get_shared_state()
    state.ui_event_queue.put(UiEvent(type=UiEventType.FIX, fix=req.fix))
    return {"status": "ok", "fix": req.fix}


@app.post("/api/ui/reset")
async def post_ui_reset() -> dict[str, str]:
    state = get_shared_state()
    state.ui_event_queue.put(UiEvent(type=UiEventType.RESET))
    return {"status": "ok", "action": "reset_requested"}
