"""tests/test_dashboard.py — tests for dashboard endpoints using FastAPI TestClient."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent.state import SharedState
from dashboard.app import app, set_shared_state


@pytest.fixture
def client():
    state = SharedState()
    set_shared_state(state)
    return TestClient(app)


def test_get_state_endpoint(client: TestClient):
    res = client.get("/api/state")
    assert res.status_code == 200
    data = res.json()
    assert "machine_id" in data
    assert "display" in data
    assert "latest_reading" in data
    assert "fix_options" in data


def test_get_timeline_endpoint(client: TestClient):
    res = client.get("/api/timeline")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_get_recalled_endpoint(client: TestClient):
    res = client.get("/api/recalled")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_get_patterns_endpoint(client: TestClient):
    res = client.get("/api/patterns")
    assert res.status_code == 200
    data = res.json()
    assert "patterns" in data


def test_trigger_sim_scenario_endpoint(client: TestClient):
    res = client.post("/api/sim/stall")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    res_invalid = client.post("/api/sim/invalid_scenario")
    assert res_invalid.status_code == 400


def test_ui_events_endpoints(client: TestClient):
    res_b = client.post("/api/ui/badge", json={"worker": "W-07"})
    assert res_b.status_code == 200

    res_f = client.post("/api/ui/fix", json={"fix": "Lubricated"})
    assert res_f.status_code == 200

    res_r = client.post("/api/ui/reset")
    assert res_r.status_code == 200
