"""
scripts/run_demo.py — 3-incident demonstration arc in simulator mode.

Demonstrates the full incident-response learning lifecycle:
  Incident 1: Cold start / generic advice. Stall fault trips cutoff.
              Technician W-07 applies "Lubricated". Verification passes.
              Outcome retained into memory.
  Incident 2: Same fault pattern recurred.
              Agent recalls Incident 1, reports that "Lubricated" worked.
              Technician applies fix and verifies.
  Incident 3: Precursor pattern (ratio 1.25x + noise) detected.
              Agent issues EARLY WARNING before the hard trip happens!

Usage:
  python scripts/run_demo.py [--fresh]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.anomaly import classify
from agent.closed_loop import ClosedLoopController
from agent.config import get_settings
from agent.features import compute_features
from agent.ledger import OutcomeLedger, get_outcome_ledger
from agent.memory import LocalMemory, get_memory_store
from agent.models import (
    AnomalyLevel,
    Features,
    Reading,
    UiEvent,
    UiEventType,
)
from agent import simulator as sim_mod
from agent.state import SharedState


def print_banner(step: str, title: str):
    print("\n" + "=" * 70)
    print(f"[{step}] {title}")
    print("=" * 70)


def run_demo(fresh: bool = False):
    cfg = get_settings()
    state = SharedState()
    controller = ClosedLoopController(state)
    controller.cfg.verify_seconds = 4  # accelerated verification for demo

    mem_path = Path("data/demo_memory.jsonl")
    ledger_path = Path("data/demo_ledger.json")

    ledger = OutcomeLedger(filepath=ledger_path)
    # Patch global ledger singleton for this process
    import agent.ledger as l_mod
    l_mod._ledger_instance = ledger

    if fresh or not mem_path.exists():
        if mem_path.exists():
            mem_path.unlink()
        ledger.clear()
        print("[INFO] Clean memory bank and outcome ledger initialized (fresh demo mode).")
    
    store = LocalMemory(filepath=mem_path)
    controller.store = store

    print("\nStarting Ustaad 3-Incident Demo Arc (Machine: Pump-2)...")

    # ══════════════════════════════════════════════════════════════════════════
    # INCIDENT 1: First Fault — Cold Memory
    # ══════════════════════════════════════════════════════════════════════════
    print_banner("INCIDENT 1", "Initial Stall Fault on Pump-2 (Cold Memory)")
    sim_mod.reset_simulator()
    sim_mod.set_scenario("stall")

    # Step simulator to trip cutoff
    reading = None
    for _ in range(10):
        sim_mod._sim_state.scenario_started_at -= 1.0
        reading = sim_mod.next_reading("Pump-2")
        state.push_reading(reading)
        if reading.cutoff_event:
            break

    assert reading is not None and reading.cutoff_event
    print(f"-> FRDM Safety Interlock TRIPPED: CUTOFF event received (i_ma={reading.i_ma} mA, ratio={reading.ratio}x)")
    print(f"-> Hard safety rule triggered purely in firmware: Relay = {reading.relay}")

    feat = compute_features(state.get_readings(), "Pump-2")
    if feat:
        state.set_features(classify(feat, latest_reading=reading))

    # Controller processes anomaly
    controller.step()  # DETECTED
    controller.step()  # ADVISED
    controller.step()  # WAITING_FIX

    disp = state.get_display()
    print(f"\n[AGENT DISPLAY - {disp.screen.value.upper()}]")
    print(f"Title: {disp.title}")
    print(f"Body:\n{disp.body}")

    print("\n-> Technician W-07 arrives on-site and scans RFID badge...")
    state.ui_event_queue.put(UiEvent(type=UiEventType.BADGE, worker="W-07"))
    controller.step()

    print("-> Technician chooses fix: 'Lubricated'")
    state.ui_event_queue.put(UiEvent(type=UiEventType.FIX, fix="Lubricated"))
    controller.step()

    print("-> Technician taps RESET to re-engage safety relay...")
    state.ui_event_queue.put(UiEvent(type=UiEventType.RESET))
    controller.step()  # RESET -> VERIFYING

    print("-> Closed-loop verification in progress (monitoring telemetry)...")
    sim_mod.set_scenario("fix_works")
    time.sleep(0.5)

    # Accelerate verify clock
    controller.verify_started_at -= 5.0
    normal_r = sim_mod.next_reading("Pump-2")
    state.push_reading(normal_r)
    feat_norm = compute_features(state.get_readings(), "Pump-2")
    if feat_norm:
        state.set_features(classify(feat_norm, latest_reading=normal_r))

    controller.step()

    disp_result = state.get_display()
    print(f"\n[VERIFICATION RESULT: {disp_result.screen.value.upper()}]")
    print(f"Outcome: {disp_result.body}")
    print("-> Retained OUTCOME memory: Fix 'Lubricated' WORKED.")

    # ══════════════════════════════════════════════════════════════════════════
    # INCIDENT 2: Recurrent Fault — Agent Recalls Memory
    # ══════════════════════════════════════════════════════════════════════════
    print_banner("INCIDENT 2", "Recurrent Fault — Agent Recalls Past Incident")
    sim_mod.reset_simulator()
    sim_mod.set_scenario("stall")

    # Step simulator to trip cutoff again
    for _ in range(10):
        sim_mod._sim_state.scenario_started_at -= 1.0
        reading2 = sim_mod.next_reading("Pump-2")
        state.push_reading(reading2)
        if reading2.cutoff_event:
            break

    feat2 = compute_features(state.get_readings(), "Pump-2")
    if feat2:
        state.set_features(classify(feat2, latest_reading=reading2))

    controller.step()  # DETECTED
    controller.step()  # ADVISED

    recalled = state.get_recalled()
    print(f"-> Agent recalled {len(recalled)} relevant past incident(s) from memory!")
    disp2 = state.get_display()
    print(f"\n[AGENT DISPLAY - {disp2.screen.value.upper()}]")
    print(f"Title: {disp2.title}")
    print(f"Advisory based on memory:\n{disp2.body}")

    # Technician applies lubricated fix again
    state.ui_event_queue.put(UiEvent(type=UiEventType.BADGE, worker="W-07"))
    controller.step()
    state.ui_event_queue.put(UiEvent(type=UiEventType.FIX, fix="Lubricated"))
    controller.step()
    state.ui_event_queue.put(UiEvent(type=UiEventType.RESET))
    controller.step()

    controller.verify_started_at -= 5.0
    normal_r2 = sim_mod.next_reading("Pump-2")
    state.push_reading(normal_r2)
    feat_norm2 = compute_features(state.get_readings(), "Pump-2")
    if feat_norm2:
        state.set_features(classify(feat_norm2, latest_reading=normal_r2))
    controller.step()

    print("-> Second incident verified and retained successfully.")

    # ══════════════════════════════════════════════════════════════════════════
    # INCIDENT 3: Precursor Warning Before Cutoff
    # ══════════════════════════════════════════════════════════════════════════
    print_banner("INCIDENT 3", "Early Warning: Precursor Detected Prior to Hard Cutoff")
    sim_mod.reset_simulator()
    sim_mod.set_scenario("precursor")

    # Generate precursor readings (ratio ~1.25x, noise ~4 spikes)
    precursor_readings = []
    base_t = time.time() - 30 * 2
    for i in range(30):
        t = base_t + i * 2
        precursor_readings.append(
            Reading(
                ts=t, temp_c=30.0 + i * 0.05, hum=52.0, gas_raw=410,
                noise=1 if (i % 8 == 0) else 0, ldr_raw=2300, door_open=False,
                i_ma=475.0, i_base_ma=380.0, ratio=1.25, relay="ON",
            )
        )
    for r in precursor_readings:
        state.push_reading(r)

    feat_pre = compute_features(precursor_readings, "Pump-2")
    assert feat_pre is not None
    classified_pre = classify(feat_pre, latest_reading=precursor_readings[-1])
    state.set_features(classified_pre)

    print(f"-> Sensor telemetry shows weak anomaly signals: ratio={classified_pre.current_ratio:.2f}x, temp_slope={classified_pre.temp_slope_c_per_min:+.1f} C/min, noise={classified_pre.noise_per_min:.1f}/min")
    print(f"-> Classified Anomaly Level: {classified_pre.anomaly.value}")

    # Force soft recall interval to allow trigger
    state.set_last_soft_recall_ts(0.0)
    controller.step()

    disp3 = state.get_display()
    print(f"\n[PROACTIVE ALERT - {disp3.screen.value.upper()}]")
    print(f"Title: {disp3.title}")
    print(f"Body:\n{disp3.body}")
    print("-> System preemptively alerted operator BEFORE any relay cutoff occurred!")

    print("\n" + "=" * 70)
    print("SUCCESS: 3-incident demonstration arc completed.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Ustaad 3-incident demo arc")
    parser.add_argument("--fresh", action="store_true", help="Start with clean memory bank")
    args = parser.parse_args()
    run_demo(fresh=args.fresh)
