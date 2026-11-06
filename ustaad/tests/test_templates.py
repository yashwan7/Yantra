"""tests/test_templates.py — tests for memory templates contract."""
from __future__ import annotations

from datetime import datetime

from agent.templates import (
    build_fix_memory,
    build_incident_memory,
    build_outcome_memory,
)


def test_incident_memory_format():
    dt = datetime(2024, 11, 1, 9, 14)
    sig = "Pump-2: current 1.5x baseline, temperature rising (+1.8 C/min), gas normal, 5 noise spikes/min, panel closed, 140 min after startup."
    text = build_incident_memory(
        machine_id="Pump-2",
        timestamp=dt,
        severity="high",
        signature=sig,
        action_taken="Overcurrent cutoff triggered, power cut",
        responder="W-07",
    )
    expected = (
        "INCIDENT | Pump-2 | 2024-11-01 09:14 | severity: high\n"
        "Signature: Pump-2: current 1.5x baseline, temperature rising (+1.8 C/min), gas normal, 5 noise spikes/min, panel closed, 140 min after startup.\n"
        "Action taken by system: Overcurrent cutoff triggered, power cut.\n"
        "Responder: W-07."
    )
    assert text == expected


def test_fix_memory_format():
    dt = datetime(2024, 11, 1, 9, 29)
    text = build_fix_memory(
        machine_id="Pump-2",
        timestamp=dt,
        worker="W-07",
        root_cause="Dry bearings",
        fix_applied="Lubricated",
    )
    expected = (
        "FIX | Pump-2 | 2024-11-01 09:29 | by W-07\n"
        "Root cause: Dry bearings. Fix applied: Lubricated."
    )
    assert text == expected


def test_outcome_memory_format():
    dt = datetime(2024, 11, 1, 10, 44)
    text = build_outcome_memory(
        machine_id="Pump-2",
        timestamp=dt,
        fix="Lubricated",
        worked=True,
        evidence="current back to 1.05x baseline for 10 min.",
    )
    expected = (
        "OUTCOME | Pump-2 | 2024-11-01 10:44\n"
        'Fix "Lubricated" WORKED. current back to 1.05x baseline for 10 min.'
    )
    assert text == expected

    text_fail = build_outcome_memory(
        machine_id="Pump-2",
        timestamp=dt,
        fix="Lubricated",
        worked=False,
        evidence="current spiked again to 1.7x.",
    )
    assert 'Fix "Lubricated" FAILED. current spiked again to 1.7x.' in text_fail

