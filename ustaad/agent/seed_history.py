"""
agent/seed_history.py — seeds historical incidents into memory.

Populates 25-30 realistic incidents over the last 60 days.
Covers:
  - Machines: Pump-2, Fan-1, Compressor-3
  - Workers: W-03, W-07, W-11, W-14, W-20
  - Key Patterns:
      1. Pump-2: Lubrication worked twice, failed third time, tightened mount fixed it.
      2. False alarm (door opened / ambient spike).
      3. Resolved without fix (transient thermal fluctuation).
      4. Precursor pattern (ratio 1.2-1.3x + noise) preceding hard cutoff faults.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from agent.ledger import get_outcome_ledger
from agent.memory import MemoryStore, get_memory_store
from agent.templates import (
    build_fix_memory,
    build_incident_memory,
    build_outcome_memory,
)

logger = logging.getLogger(__name__)


def seed_memory(store: MemoryStore, ledger_path: str = "data/outcome_ledger.json") -> int:
    """Seed synthetic history into the memory store and outcome ledger. Returns count of entries."""
    logger.info("Seeding historical incidents into memory store and ledger...")
    ledger = get_outcome_ledger(ledger_path)
    ledger.clear()

    now = datetime.utcnow()
    entries_count = 0

    def add_triplet(
        machine_id: str,
        dt: datetime,
        severity: str,
        sig: str,
        action: str,
        worker: str,
        root_cause: str,
        fix: str,
        worked: bool,
        evidence: str,
        tags: list[str] | None = None,
        is_precursor: bool = False,
    ):
        nonlocal entries_count
        base_tags = [
            f"machine:{machine_id}",
            f"worker:{worker}",
            f"fix:{fix.lower()}",
            f"result:{'worked' if worked else 'failed'}",
        ]
        if tags:
            base_tags.extend(tags)

        inc_text = build_incident_memory(machine_id, dt, severity, sig, action, worker)
        fix_text = build_fix_memory(machine_id, dt + timedelta(minutes=15), worker, root_cause, fix)
        out_text = build_outcome_memory(machine_id, dt + timedelta(minutes=75), fix, worked, evidence)

        metadata_common = {
            "machine": machine_id,
            "worker": worker,
            "fix": fix,
            "result": "worked" if worked else "failed",
        }

        store.retain(inc_text, timestamp=dt, tags=base_tags, metadata=metadata_common)
        store.retain(fix_text, timestamp=dt + timedelta(minutes=15), tags=base_tags, metadata=metadata_common)
        store.retain(out_text, timestamp=dt + timedelta(minutes=75), tags=base_tags, metadata=metadata_common)

        # Record into deterministic ledger
        ts_base = dt.timestamp()
        ledger.record_incident(machine_id, sig, ts_base, is_precursor=is_precursor, worker=worker)
        ledger.record_fix(machine_id, fix, worker, ts_base + 900, signature=sig)
        ledger.record_outcome(machine_id, fix, worked, ts_base + 4500, evidence, worker=worker)

        entries_count += 3

    # ── Incidents 1 & 2: Pump-2 Bearing Lubrication Worked ─────────────────────
    dt1 = now - timedelta(days=52, hours=4)
    sig1 = "Pump-2: current 1.5x baseline, temperature rising (+1.8 C/min), gas normal, 5 noise spikes/min, panel closed, 140 min after startup."
    add_triplet(
        "Pump-2", dt1, "high", sig1, "Overcurrent cutoff triggered, power cut", "W-03",
        "Dry motor bearings causing friction drag", "Lubricated", True,
        "current back to 1.02x baseline for 4 hours", ["type:bearing", "pattern:lubrication"],
    )

    dt2 = now - timedelta(days=38, hours=2)
    sig2 = "Pump-2: current 1.6x baseline, temperature rising (+2.1 C/min), gas normal, 6 noise spikes/min, panel closed, 210 min after startup."
    add_triplet(
        "Pump-2", dt2, "high", sig2, "Overcurrent cutoff triggered, relay opened", "W-07",
        "Bearing friction increase observed after extended run", "Lubricated", True,
        "current stabilized at 1.04x baseline for 24 hours", ["type:bearing", "pattern:lubrication"],
    )

    # ── Incident 3: Pump-2 Lubrication FAILED 3rd time; mount tightened WORKED ──
    dt3 = now - timedelta(days=22, hours=6)
    sig3 = "Pump-2: current 1.6x baseline, temperature rising (+2.4 C/min), gas normal, 7 noise spikes/min, panel closed, 95 min after startup."
    ts3 = dt3.timestamp()
    inc3 = build_incident_memory("Pump-2", dt3, "high", sig3, "Overcurrent cutoff triggered", "W-07")
    fix3a = build_fix_memory("Pump-2", dt3 + timedelta(minutes=10), "W-07", "Assumed bearing wear", "Lubricated")
    out3a = build_outcome_memory("Pump-2", dt3 + timedelta(minutes=40), "Lubricated", False, "current surged back to 1.7x baseline within 20 minutes")
    tags3a = ["machine:Pump-2", "worker:W-07", "fix:lubricated", "result:failed"]
    meta3a = {"machine": "Pump-2", "worker": "W-07", "fix": "Lubricated", "result": "failed"}
    store.retain(inc3, timestamp=dt3, tags=tags3a, metadata=meta3a)
    store.retain(fix3a, timestamp=dt3 + timedelta(minutes=10), tags=tags3a, metadata=meta3a)
    store.retain(out3a, timestamp=dt3 + timedelta(minutes=40), tags=tags3a, metadata=meta3a)
    ledger.record_incident("Pump-2", sig3, ts3, worker="W-07")
    ledger.record_fix("Pump-2", "Lubricated", "W-07", ts3 + 600, signature=sig3)
    ledger.record_outcome("Pump-2", "Lubricated", False, ts3 + 2400, "current surged back to 1.7x baseline within 20 minutes", worker="W-07")
    entries_count += 3

    # Then mount tightened, worked
    fix3b = build_fix_memory("Pump-2", dt3 + timedelta(minutes=50), "W-11", "Loose mounting bolts causing rotor misalignment", "Tightened mount")
    out3b = build_outcome_memory("Pump-2", dt3 + timedelta(minutes=110), "Tightened mount", True, "vibration zeroed and current steady at 1.01x baseline")
    tags3b = ["machine:Pump-2", "worker:W-11", "fix:tightened mount", "result:worked"]
    meta3b = {"machine": "Pump-2", "worker": "W-11", "fix": "Tightened mount", "result": "worked"}
    store.retain(fix3b, timestamp=dt3 + timedelta(minutes=50), tags=tags3b, metadata=meta3b)
    store.retain(out3b, timestamp=dt3 + timedelta(minutes=110), tags=tags3b, metadata=meta3b)
    ledger.record_fix("Pump-2", "Tightened mount", "W-11", ts3 + 3000, signature=sig3)
    ledger.record_outcome("Pump-2", "Tightened mount", True, ts3 + 6600, "vibration zeroed and current steady at 1.01x baseline", worker="W-11")
    entries_count += 2

    # ── Incident 4: False Alarm (door opened during inspection) ────────────────
    dt4 = now - timedelta(days=18, hours=3)
    sig4 = "Fan-1: current 1.0x baseline, temperature stable (+0.1 C/min), gas normal, 0 noise spikes/min, panel open, 60 min after startup."
    add_triplet(
        "Fan-1", dt4, "low", sig4, "Enclosure panel open alert", "W-14",
        "Routine visual inspection panel left unlatched", "Other", True,
        "panel latched closed, all readings nominal", ["type:false_alarm"],
    )

    # ── Incident 5: Resolved without fix (transient thermal fluctuation) ────────
    dt5 = now - timedelta(days=15, hours=8)
    sig5 = "Compressor-3: current 1.1x baseline, temperature rising (+1.2 C/min), gas normal, 1 noise spikes/min, panel closed, 180 min after startup."
    add_triplet(
        "Compressor-3", dt5, "medium", sig5, "Transient thermal warning", "W-03",
        "HVAC ambient temperature spike during afternoon sun", "Other", True,
        "temperature settled to ambient without mechanical intervention", ["type:transient"],
    )

    # ── Incidents 6 & 7: Precursor pattern before real cutoffs ─────────────────
    dt6 = now - timedelta(days=11, hours=5)
    sig6 = "Pump-2: current 1.2x baseline, temperature rising (+1.4 C/min), gas normal, 4 noise spikes/min, panel closed, 45 min after startup."
    add_triplet(
        "Pump-2", dt6, "medium", sig6, "Soft anomaly warning issued to operator", "W-07",
        "Precursor mechanical drag on pump impeller", "Cleared blockage", True,
        "impeller cleared of debris, current returned to 1.01x baseline", ["type:precursor"],
    )

    dt7 = now - timedelta(days=7, hours=1)
    sig7 = "Fan-1: current 1.3x baseline, temperature rising (+1.6 C/min), gas normal, 5 noise spikes/min, panel closed, 80 min after startup."
    add_triplet(
        "Fan-1", dt7, "medium", sig7, "Precursor acoustic and current deviation noted", "W-20",
        "Foreign particulate accumulation on belt drive", "Cleared blockage", True,
        "belt wiped and tensioned, ratio steady at 1.03x", ["type:precursor"],
    )

    # ── Additional Incidents to reach 25-30 total entries ───────────────────────
    dt8 = now - timedelta(days=4, hours=10)
    sig8 = "Compressor-3: current 1.7x baseline, temperature rising (+3.2 C/min), gas elevated, 9 noise spikes/min, panel closed, 30 min after startup."
    add_triplet(
        "Compressor-3", dt8, "high", sig8, "Overcurrent hard trip", "W-11",
        "Exhaust valve seal blowout causing motor overload", "Replaced part", True,
        "replaced discharge valve plate, pressure and current normal for 48 hours",
    )

    dt9 = now - timedelta(days=2, hours=3)
    sig9 = "Fan-1: current 1.5x baseline, temperature rising (+2.0 C/min), gas normal, 4 noise spikes/min, panel closed, 120 min after startup."
    add_triplet(
        "Fan-1", dt9, "high", sig9, "Thermal and current threshold crossed", "W-03",
        "Drive pulley set-screw loosened causing slippage", "Tightened mount", True,
        "pulley re-aligned and torqued, ratio 1.02x",
    )

    logger.info("Successfully seeded %d historical memory entries", entries_count)
    return entries_count


if __name__ == "__main__":
    store = get_memory_store()
    seed_memory(store)

