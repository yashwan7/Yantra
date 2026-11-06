"""tests/test_simulator.py — unit tests for simulator scenarios."""
from __future__ import annotations

import time
import pytest

from agent import simulator as sim_mod


def test_baseline_readings():
    sim_mod.reset_simulator()
    r = sim_mod.next_reading("Pump-2")
    assert 340 <= r.i_ma <= 420
    assert 28.0 <= r.temp_c <= 32.0
    assert r.relay == "ON"
    assert not r.cutoff_event
    assert not r.door_open


def test_stall_scenario_cutoff():
    sim_mod.reset_simulator()
    sim_mod.set_scenario("stall")
    # simulate time progression
    cutoff_seen = False
    for i in range(12):
        # advance scenario_started_at backward
        sim_mod._sim_state.scenario_started_at -= 1.0
        r = sim_mod.next_reading("Pump-2")
        if r.cutoff_event:
            cutoff_seen = True
            assert r.relay == "OFF"
            assert r.cutoff_reason == "OVERCURRENT"
            break
    assert cutoff_seen
    assert sim_mod._sim_state.relay_latched

    # Reset
    sim_mod.apply_reset("W-07")
    assert not sim_mod._sim_state.relay_latched
    r_after = sim_mod.next_reading("Pump-2")
    assert r_after.relay == "ON"


def test_door_scenario():
    sim_mod.reset_simulator()
    sim_mod.set_scenario("door")
    r = sim_mod.next_reading("Pump-2")
    assert r.door_open is True


def test_gas_scenario():
    sim_mod.reset_simulator()
    sim_mod.set_scenario("gas")
    r = sim_mod.next_reading("Pump-2")
    assert r.gas_raw > 550

