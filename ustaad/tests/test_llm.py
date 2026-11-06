"""tests/test_llm.py — tests for LLM advisory, tools, and fallback handling."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from agent.llm import MockLLM, build_template_advice, LlmAdvisor
from agent.models import AnomalyLevel, Features, Incident, Memory, Reading, RiskLevel, ScreenType
from agent.state import SharedState
from agent.tools import ToolRegistry, TOOL_SCHEMAS


def test_tool_schemas_valid():
    assert len(TOOL_SCHEMAS) == 5
    names = [t["function"]["name"] for t in TOOL_SCHEMAS]
    assert "get_live_readings" in names
    assert "recall_incidents" in names
    assert "retain_incident" in names
    assert "show_on_display" in names
    assert "request_relay_reset" in names


def test_template_advice_counts_and_fixes():
    memories = [
        Memory(
            id="1",
            text="INCIDENT | Pump-2 | 2024-11-01 09:14 | severity: high\nSignature: ...\n"
                 "FIX | Pump-2 | 2024-11-01 09:29 | by W-07\nRoot cause: wear. Fix applied: Lubricated.\n"
                 "OUTCOME | Pump-2 | 2024-11-01 10:44\nFix \"Lubricated\" WORKED. current back to 1.05x.",
        ),
        Memory(
            id="2",
            text="INCIDENT | Pump-2 | 2024-11-10 14:00 | severity: high\nSignature: ...\n"
                 "FIX | Pump-2 | 2024-11-10 14:15 | by W-07\nRoot cause: wear. Fix applied: Lubricated.\n"
                 "OUTCOME | Pump-2 | 2024-11-10 15:30\nFix \"Lubricated\" FAILED. current surged back.",
        ),
    ]

    advice = build_template_advice("Pump-2", "Pump-2 signature", memories, is_precursor=False)
    assert "Recalled 2 similar past incidents" in advice
    assert "Lubricated" in advice
    assert "1 WORKED, 1 FAILED" in advice


def test_request_relay_reset_refused_without_badge():
    state = SharedState()
    reg = ToolRegistry(state)

    # No incident or badged worker
    res = json.loads(reg.execute("request_relay_reset", {"worker_id": "W-07"}))
    assert res["status"] == "refused"
    assert "not badged in" in res["reason"]

    # Now set incident with badged worker
    inc = Incident(
        incident_id="inc-1",
        machine_id="Pump-2",
        detected_at=__import__("datetime").datetime.utcnow(),
        signature="sig",
        severity="high",
        anomaly_level=AnomalyLevel.HARD,
        features=Features(
            ts=100.0, machine_id="Pump-2", current_ratio=1.5, temp_slope_c_per_min=0.0,
            gas_delta=0.0, noise_per_min=0.0, door_open=False, uptime_min=10.0,
        ),
        worker_id="W-07",
    )
    state.set_incident(inc)

    res_ok = json.loads(reg.execute("request_relay_reset", {"worker_id": "W-07"}))
    assert res_ok["status"] == "accepted"

    # Different worker should still be refused
    res_wrong = json.loads(reg.execute("request_relay_reset", {"worker_id": "W-99"}))
    assert res_wrong["status"] == "refused"


def test_show_on_display_tool():
    state = SharedState()
    reg = ToolRegistry(state)

    res = json.loads(reg.execute("show_on_display", {"title": "Check Motor", "body": "Bearing hot", "risk": "HIGH"}))
    assert res["status"] == "displayed"
    disp = state.get_display()
    assert disp.title == "Check Motor"
    assert disp.body == "Bearing hot"
    assert disp.risk == RiskLevel.HIGH


def test_mock_llm():
    mock = MockLLM(canned_response="Check bolts immediately.")
    res = mock.generate_advice("Pump-2", "sig", [])
    assert res == "Check bolts immediately."
    assert mock.call_count == 1
