"""
agent/simulator.py — in-process sensor + FRDM simulator.

Produces a stream of Reading objects without any real hardware.
Triggered scenarios are set via SharedState.set_scenario().

Scenarios:
  stall       — current ramps to 1.9× in ~8 s, then CUTOFF event (relay latched)
  precursor   — ratio 1.2-1.3×, noise 3-5/min, temp +1.5 C/min for ~40 s, then recovers
  gas         — gas_raw spikes > 500 for ~30 s
  door        — door_open = True for ~20 s
  heat        — temp_slope_c_per_min > 3 for ~40 s
  fix_works   — after RESET: returns to normal immediately
  fix_fails   — after RESET: returns to anomaly after ~60 s
"""
from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Optional

from agent.models import Reading

logger = logging.getLogger(__name__)

# ── Baseline parameters ───────────────────────────────────────────────────────
_BASE_CURRENT_MA: float = 380.0
_BASE_TEMP_C: float = 30.0
_BASE_HUM: float = 52.0
_BASE_GAS: int = 410
_BASE_LDR: int = 2300
_NOISE_RATE: float = 0.5           # avg spikes per 2-s tick at baseline


@dataclass
class SimulatorState:
    scenario: Optional[str] = None
    scenario_started_at: float = field(default_factory=time.time)
    relay_latched: bool = False         # True after CUTOFF until RESET
    relay_on_since: float = field(default_factory=time.time)
    post_reset_scenario: Optional[str] = None  # fix_works / fix_fails
    fix_applied_at: float = 0.0
    cutoff_emitted: bool = False


_sim_state = SimulatorState()


def set_scenario(name: str) -> None:
    """Set the active scenario (called from dashboard or CLI)."""
    global _sim_state
    logger.info("Simulator scenario → %s", name)
    if name in ("fix_works", "fix_fails"):
        _sim_state.post_reset_scenario = name
        _sim_state.fix_applied_at = time.time()
    else:
        _sim_state.scenario = name
        _sim_state.scenario_started_at = time.time()
        _sim_state.cutoff_emitted = False


def apply_reset(worker: str) -> None:
    """Called when a RESET command is sent; unlatches relay."""
    global _sim_state
    logger.info("Simulator RESET by %s", worker)
    _sim_state.relay_latched = False
    _sim_state.relay_on_since = time.time()
    _sim_state.scenario = None
    _sim_state.cutoff_emitted = False


def _add_noise(val: float, sigma: float) -> float:
    return val + random.gauss(0, sigma)


def next_reading(machine_id: str) -> Reading:
    """
    Generate the next simulated Reading.

    Returns a CUTOFF event reading when the stall scenario reaches trip
    threshold (only once per scenario activation).
    """
    global _sim_state
    now = time.time()
    elapsed = now - _sim_state.scenario_started_at

    # --- defaults (normal baseline) ---
    current = _add_noise(_BASE_CURRENT_MA, 8.0)
    temp = _add_noise(_BASE_TEMP_C, 0.3)
    hum = _add_noise(_BASE_HUM, 1.0)
    gas = int(_add_noise(_BASE_GAS, 15.0))
    noise_flag = 1 if random.random() < _NOISE_RATE * (2 / 60) else 0
    door_open = False
    cutoff_event = False
    cutoff_reason: Optional[str] = None
    relay = "OFF" if _sim_state.relay_latched else "ON"

    s = _sim_state.scenario

    # ── stall scenario ────────────────────────────────────────────────────────
    if s == "stall" and not _sim_state.relay_latched:
        ramp = min(elapsed / 8.0, 1.0)             # 0 → 1 over 8 s
        current = _BASE_CURRENT_MA * (1.0 + ramp * 0.9)   # up to 1.9×
        temp = _BASE_TEMP_C + elapsed * 0.4         # mild temp rise
        if current >= _BASE_CURRENT_MA * 1.8 and not _sim_state.cutoff_emitted:
            # Simulate FRDM trip after 3 consecutive samples (we do it in one shot)
            cutoff_event = True
            cutoff_reason = "OVERCURRENT"
            _sim_state.relay_latched = True
            _sim_state.cutoff_emitted = True
            relay = "OFF"
            logger.info("Simulator: CUTOFF event emitted (stall)")

    # ── precursor scenario ────────────────────────────────────────────────────
    elif s == "precursor":
        if elapsed < 40.0:
            current = _BASE_CURRENT_MA * (1.2 + 0.1 * math.sin(elapsed))
            temp = _BASE_TEMP_C + elapsed * 0.025   # ~1.5 C/min
            noise_flag = 1 if random.random() < 4 / 60 else 0  # ~4/min
        else:
            # recovers naturally
            _sim_state.scenario = None

    # ── gas scenario ──────────────────────────────────────────────────────────
    elif s == "gas":
        if elapsed < 30.0:
            gas = int(_add_noise(650, 20))
        else:
            _sim_state.scenario = None

    # ── door scenario ─────────────────────────────────────────────────────────
    elif s == "door":
        if elapsed < 20.0:
            door_open = True
        else:
            _sim_state.scenario = None

    # ── heat scenario ─────────────────────────────────────────────────────────
    elif s == "heat":
        if elapsed < 40.0:
            temp = _BASE_TEMP_C + elapsed * 0.065   # ~3.9 C/min
        else:
            _sim_state.scenario = None

    # ── post-reset scenarios ──────────────────────────────────────────────────
    if _sim_state.post_reset_scenario == "fix_works":
        # stays normal — no changes needed
        pass
    elif _sim_state.post_reset_scenario == "fix_fails":
        since_fix = now - _sim_state.fix_applied_at
        if since_fix > 60.0:
            current = _BASE_CURRENT_MA * (1.5 + 0.1 * min((since_fix - 60) / 20, 1.0))

    baseline = _BASE_CURRENT_MA
    ratio = current / baseline

    return Reading(
        ts=now,
        temp_c=round(temp, 2),
        hum=round(max(0.0, min(100.0, hum)), 1),
        gas_raw=max(0, gas),
        noise=noise_flag,
        ldr_raw=_BASE_LDR,
        door_open=door_open,
        i_ma=round(current, 1),
        i_base_ma=round(baseline, 1),
        ratio=round(ratio, 3),
        relay=relay,
        cutoff_event=cutoff_event,
        cutoff_reason=cutoff_reason,
        source="sim",
    )


def reset_simulator() -> None:
    """Reset to a clean baseline (used between test scenarios)."""
    global _sim_state
    _sim_state = SimulatorState()
    logger.info("Simulator reset to baseline")

