"""
agent/tools.py — tool definitions, JSON schemas, and execution handlers.

Tools:
  - get_live_readings(): returns latest sensor measurements
  - recall_incidents(query): searches memory store for past cases
  - retain_incident(text): stores an incident memory record
  - show_on_display(title, body): updates the hardware / virtual display
  - request_relay_reset(worker_id): requests relay reset, refused unless worker badged in
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from agent.memory import get_memory_store
from agent.models import RiskLevel, ScreenType, UiDisplay
from agent.state import SharedState

logger = logging.getLogger(__name__)


# ── Tool Definitions (OpenAI / Groq Function Calling Schema) ───────────────────

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_live_readings",
            "description": "Fetch the most recent live sensor readings and computed features for the machine.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_incidents",
            "description": "Search Hindsight persistent memory for past incidents matching a symptom query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query describing symptoms, e.g. 'Pump-2 current ratio rising temperature'",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of matching memories to return (default 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retain_incident",
            "description": "Retain an incident report or observation into persistent memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The formatted memory string to retain",
                    },
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_on_display",
            "description": "Update the on-machine display or virtual TFT screen with an advisory message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short title (under 24 chars)"},
                    "body": {"type": "string", "description": "Message body to show technician"},
                    "risk": {
                        "type": "string",
                        "enum": ["LOW", "MED", "HIGH"],
                        "description": "Risk level",
                    },
                },
                "required": ["title", "body"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_relay_reset",
            "description": "Request a relay reset after a trip. REFUSED unless the specified worker has already badged in on-site.",
            "parameters": {
                "type": "object",
                "properties": {
                    "worker_id": {
                        "type": "string",
                        "description": "Identifier of the technician requesting the reset, e.g. 'W-07'",
                    },
                },
                "required": ["worker_id"],
                "additionalProperties": False,
            },
        },
    },
]


class ToolRegistry:
    """Dispatches tool execution against agent state and memory store."""

    def __init__(self, state: SharedState) -> None:
        self.state = state

    def get_live_readings(self) -> dict[str, Any]:
        reading = self.state.latest_reading()
        feat = self.state.get_features()
        return {
            "latest_reading": {
                "temp_c": reading.temp_c if reading else None,
                "hum": reading.hum if reading else None,
                "gas_raw": reading.gas_raw if reading else None,
                "noise": reading.noise if reading else None,
                "i_ma": reading.i_ma if reading else None,
                "ratio": reading.ratio if reading else None,
                "relay": reading.relay if reading else None,
            } if reading else {},
            "features": {
                "current_ratio": feat.current_ratio if feat else None,
                "temp_slope_c_per_min": feat.temp_slope_c_per_min if feat else None,
                "gas_delta": feat.gas_delta if feat else None,
                "noise_per_min": feat.noise_per_min if feat else None,
                "uptime_min": feat.uptime_min if feat else None,
                "anomaly": feat.anomaly.value if feat else "NONE",
            } if feat else {},
        }

    def recall_incidents(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        store = get_memory_store()
        memories = store.recall(query, limit=limit)
        return [{"id": m.id, "text": m.text, "score": m.score} for m in memories]

    def retain_incident(self, text: str) -> dict[str, Any]:
        store = get_memory_store()
        store.retain(text)
        return {"status": "retained", "length": len(text)}

    def show_on_display(self, title: str, body: str, risk: str = "MED") -> dict[str, Any]:
        risk_enum = RiskLevel(risk) if risk in ("LOW", "MED", "HIGH") else RiskLevel.MED
        self.state.set_display(
            UiDisplay(
                screen=ScreenType.ALERT,
                title=title,
                body=body,
                risk=risk_enum,
            )
        )
        return {"status": "displayed", "title": title}

    def request_relay_reset(self, worker_id: str) -> dict[str, Any]:
        inc = self.state.get_incident()
        badged_worker = inc.worker_id if inc else None

        # Check if the worker is badged in
        if not badged_worker or badged_worker != worker_id:
            logger.warning(
                "Relay reset REFUSED for worker '%s'. Badged worker is '%s'",
                worker_id,
                badged_worker,
            )
            return {
                "status": "refused",
                "reason": f"Worker {worker_id} has not badged in. On-site RFID badge required before reset.",
            }

        # In simulator mode, apply reset to simulator
        from agent.simulator import apply_reset
        apply_reset(worker_id)
        return {"status": "accepted", "worker": worker_id}

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        handlers: dict[str, Callable[..., Any]] = {
            "get_live_readings": self.get_live_readings,
            "recall_incidents": self.recall_incidents,
            "retain_incident": self.retain_incident,
            "show_on_display": self.show_on_display,
            "request_relay_reset": self.request_relay_reset,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return json.dumps({"error": f"Unknown tool '{tool_name}'"})

        try:
            res = handler(**arguments)
            return json.dumps(res)
        except Exception as e:
            logger.exception("Error executing tool %s", tool_name)
            return json.dumps({"error": str(e)})
