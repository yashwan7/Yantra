"""
tests/test_learning_arc.py — tests for the cold start and persistent learning arc.

Verifies:
  (a) fresh run -> Incident 1 advice is generic, contains no historical counts, and no "historical outcomes" text.
  (b) after one WORKED outcome, Incident 2 advice mentions it with count 1 WORKED, 0 FAILED.
  (c) ledger and bank id are paired; separate bank ids do not share memory or outcomes.
"""
from __future__ import annotations

import time
from pathlib import Path

from agent.closed_loop import ClosedLoopController
from agent.ledger import OutcomeLedger, get_outcome_ledger
from agent.llm import build_template_advice
from agent.memory import LocalMemory, get_memory_store
from agent.models import (
    AnomalyLevel,
    Features,
    LoopState,
    Reading,
    RiskLevel,
    UiEvent,
    UiEventType,
)
from agent.state import SharedState


def test_bank_pairing(tmp_path: Path):
    """(c) Ledger and bank ID are paired; distinct banks maintain isolated ledgers."""
    ledger1 = OutcomeLedger(bank_id="bank-alpha", filepath=tmp_path / "ledger_alpha.json")
    ledger2 = OutcomeLedger(bank_id="bank-beta", filepath=tmp_path / "ledger_beta.json")

    ledger1.record_outcome("Pump-2", "Lubricated", True, 1000.0, "worked")
    stats1 = ledger1.get_stats("Pump-2")
    stats2 = ledger2.get_stats("Pump-2")

    assert stats1["fix_outcomes"]["Lubricated"]["worked"] == 1
    assert "Lubricated" not in stats2["fix_outcomes"]
    assert stats2["total_incidents"] == 0


def test_cold_start_generic_advice(tmp_path: Path):
    """(a) Fresh run -> Incident 1 advice contains NO historical counts and NO 'historical outcomes' text."""
    empty_ledger = OutcomeLedger(bank_id="bank-fresh", filepath=tmp_path / "ledger_fresh.json")
    
    # Hindsight recall returns nothing relevant (cold start)
    recalled_empty = []
    
    advice = build_template_advice(
        machine_id="Pump-2",
        signature="Pump-2: current 1.8x baseline, temperature rising, panel closed",
        recalled=recalled_empty,
        is_precursor=False,
        ledger=empty_ledger,
    )

    # Must be generic
    assert "historical outcomes" not in advice
    assert "WORKED" not in advice
    assert "FAILED" not in advice
    assert "No prior matching incidents in memory" in advice
    assert "Recommend immediate visual inspection" in advice


def test_learning_arc_first_and_second_incident(tmp_path: Path):
    """(b) After one WORKED outcome, Incident 2 advice mentions it with count 1 WORKED, 0 FAILED."""
    bank_id = f"test-arc-{int(time.time() * 1000)}"
    store = LocalMemory(bank_id=bank_id, filepath=tmp_path / f"mem_{bank_id}.jsonl")
    ledger = OutcomeLedger(bank_id=bank_id, filepath=tmp_path / f"ledger_{bank_id}.json")

    state = SharedState()
    clock_time = 1000.0
    controller = ClosedLoopController(
        state,
        clock=lambda: clock_time,
        bank_id=bank_id,
        store=store,
        ledger=ledger,
    )
    controller.cfg.verify_seconds = 5

    # ── Incident 1: Cold start ────────────────────────────────────────────────
    feat = Features(
        ts=clock_time, machine_id="Pump-2", current_ratio=1.9, temp_slope_c_per_min=2.0,
        gas_delta=0.0, noise_per_min=5.0, door_open=False, uptime_min=10.0,
        anomaly=AnomalyLevel.HARD, risk=RiskLevel.HIGH,
    )
    state.set_features(feat)
    state.push_reading(Reading(
        ts=clock_time, temp_c=30.0, hum=50.0, gas_raw=410, noise=0,
        ldr_raw=2300, door_open=False, i_ma=720.0, i_base_ma=380.0,
        ratio=1.9, relay="OFF", cutoff_event=True, cutoff_reason="OVERCURRENT",
    ))

    controller.step()  # DETECTED
    controller.step()  # ADVISED
    controller.step()  # WAITING_FIX

    inc1 = state.get_incident()
    assert inc1 is not None
    # Incident 1 advice must be strictly generic!
    assert "historical outcomes" not in inc1.advice
    assert "No prior matching incidents in memory" in inc1.advice

    # Apply fix Lubricated and reset
    state.ui_event_queue.put(UiEvent(type=UiEventType.BADGE, worker="W-07"))
    controller.step()
    state.ui_event_queue.put(UiEvent(type=UiEventType.FIX, fix="Lubricated"))
    controller.step()
    state.ui_event_queue.put(UiEvent(type=UiEventType.RESET))
    controller.step()

    # Pass verification
    clock_time += 6.0
    state.set_features(Features(
        ts=clock_time, machine_id="Pump-2", current_ratio=1.02, temp_slope_c_per_min=0.1,
        gas_delta=0.0, noise_per_min=0.0, door_open=False, uptime_min=10.1,
        anomaly=AnomalyLevel.NONE, risk=RiskLevel.LOW,
    ))
    controller.step()

    # Outcome WORKED has been retained
    assert controller.current_state == LoopState.IDLE
    stats_after_1 = ledger.get_stats("Pump-2")
    assert stats_after_1["fix_outcomes"]["Lubricated"]["worked"] == 1
    assert stats_after_1["fix_outcomes"]["Lubricated"]["failed"] == 0

    # ── Incident 2: Recurrent fault on same bank ──────────────────────────────
    clock_time += 100.0
    state.set_features(Features(
        ts=clock_time, machine_id="Pump-2", current_ratio=1.9, temp_slope_c_per_min=2.0,
        gas_delta=0.0, noise_per_min=5.0, door_open=False, uptime_min=12.0,
        anomaly=AnomalyLevel.HARD, risk=RiskLevel.HIGH,
    ))
    state.push_reading(Reading(
        ts=clock_time, temp_c=32.0, hum=50.0, gas_raw=410, noise=0,
        ldr_raw=2300, door_open=False, i_ma=720.0, i_base_ma=380.0,
        ratio=1.9, relay="OFF", cutoff_event=True, cutoff_reason="OVERCURRENT",
    ))

    controller.step()  # DETECTED
    controller.step()  # ADVISED

    inc2 = state.get_incident()
    assert inc2 is not None
    # Incident 2 must recall Incident 1 and report 1 WORKED, 0 FAILED!
    assert "Lubricated" in inc2.advice
    assert "1 WORKED, 0 FAILED" in inc2.advice
