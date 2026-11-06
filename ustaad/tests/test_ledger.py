"""tests/test_ledger.py — unit tests for deterministic outcome ledger."""
from __future__ import annotations

from pathlib import Path

from agent.ledger import OutcomeLedger


def test_outcome_ledger_counts(tmp_path: Path):
    ledger_file = tmp_path / "test_ledger.json"
    ledger = OutcomeLedger(filepath=ledger_file)

    ledger.record_incident("Pump-2", "sig1", 1000.0, is_precursor=False)
    ledger.record_fix("Pump-2", "Lubricated", "W-07", 1100.0)
    ledger.record_outcome("Pump-2", "Lubricated", True, 1200.0, "normal current")

    ledger.record_incident("Pump-2", "sig2", 2000.0, is_precursor=False)
    ledger.record_fix("Pump-2", "Lubricated", "W-07", 2100.0)
    ledger.record_outcome("Pump-2", "Lubricated", False, 2200.0, "current spiked")

    ledger.record_incident("Pump-2", "sig3", 3000.0, is_precursor=True)

    stats = ledger.get_stats("Pump-2")
    assert stats["total_incidents"] == 3
    assert stats["total_precursors"] == 1
    assert stats["last_fix"] == "Lubricated"
    assert stats["fix_outcomes"]["Lubricated"]["worked"] == 1
    assert stats["fix_outcomes"]["Lubricated"]["failed"] == 1

    # Reload from disk
    reloaded = OutcomeLedger(filepath=ledger_file)
    stats2 = reloaded.get_stats("Pump-2")
    assert stats2["total_incidents"] == 3
    assert stats2["fix_outcomes"]["Lubricated"]["worked"] == 1

