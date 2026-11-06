"""tests/test_memory.py — unit tests for LocalMemory store."""
from __future__ import annotations

from pathlib import Path

from agent.memory import LocalMemory


def test_local_memory_retain_and_recall(tmp_path: Path):
    mem_file = tmp_path / "test_memory.jsonl"
    store = LocalMemory(filepath=mem_file)

    text1 = (
        "INCIDENT | Pump-2 | 2024-11-01 09:14 | severity: high\n"
        "Signature: Pump-2: current 1.5x baseline, temperature rising (+1.8 C/min), "
        "gas normal, 5 noise spikes/min, panel closed, 140 min after startup.\n"
        "Action taken by system: Overcurrent cutoff triggered.\n"
        "Responder: W-07."
    )
    text2 = (
        "INCIDENT | Fan-1 | 2024-11-02 12:00 | severity: low\n"
        "Signature: Fan-1: current 1.0x baseline, temperature stable (+0.1 C/min), "
        "gas normal, 0 noise spikes/min, panel open, 60 min after startup.\n"
        "Action taken by system: Enclosure panel open alert.\n"
        "Responder: W-14."
    )

    store.retain(text1, tags=["machine:Pump-2", "worker:W-07"])
    store.retain(text2, tags=["machine:Fan-1", "worker:W-14"])

    # Query for Pump-2 current
    recalled = store.recall("Pump-2 current temperature rising baseline", limit=5)
    assert len(recalled) >= 1
    assert recalled[0].text == text1
    assert recalled[0].score > 0

    # Test file reload
    reloaded = LocalMemory(filepath=mem_file)
    assert len(reloaded._entries) == 2


def test_local_memory_reflect(tmp_path: Path):
    mem_file = tmp_path / "test_reflect.jsonl"
    store = LocalMemory(filepath=mem_file)

    store.retain("INCIDENT | Pump-2 | 2024-11-01 09:14 | severity: high")
    store.retain("FIX | Pump-2 | 2024-11-01 09:29 | by W-07\nRoot cause: wear. Fix applied: Lubricated.")
    store.retain("OUTCOME | Pump-2 | 2024-11-01 10:44\nFix \"Lubricated\" WORKED. current back to 1.05x baseline.")

    summary = store.reflect("What are the outcomes?")
    assert "1 worked" in summary
    assert "Lubricated" in summary
