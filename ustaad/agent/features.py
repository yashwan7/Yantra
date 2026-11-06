"""
agent/features.py — compute features over a 60-second rolling window.

Called every 2 seconds with the latest readings list from SharedState.
Pure functions (no I/O) so they are easy to unit-test.
"""
from __future__ import annotations

import logging
import math
import time
from statistics import median
from typing import Sequence

from agent.models import AnomalyLevel, Features, Reading, RiskLevel

logger = logging.getLogger(__name__)

# Window parameters
WINDOW_S: float = 60.0          # rolling window length
BASELINE_S: float = 30.0        # first 30 s used for gas baseline


def _linear_slope(xs: list[float], ys: list[float]) -> float:
    """Return slope of OLS linear regression (ΔY / ΔX)."""
    n = len(xs)
    if n < 2:
        return 0.0
    x0 = xs[0]
    norm_xs = [x - x0 for x in xs]
    sx = sum(norm_xs)
    sy = sum(ys)
    sxx = sum(x * x for x in norm_xs)
    sxy = sum(x * y for x, y in zip(norm_xs, ys))
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-9:
        return 0.0
    return (n * sxy - sx * sy) / denom


def compute_features(
    readings: Sequence[Reading],
    machine_id: str,
    relay_on_since: float | None = None,
) -> Features | None:
    """
    Compute features from the most recent readings.

    Returns None if there are fewer than 3 readings (not enough data).
    """
    if not readings or len(readings) < 3:
        return None

    now = readings[-1].ts
    cutoff_time = now - WINDOW_S

    # Window: readings within the last 60 s
    window = [r for r in readings if r.ts >= cutoff_time]
    if len(window) < 3:
        window = list(readings[-15:])   # fallback: last 15 readings

    # ── current ratio ─────────────────────────────────────────────────────────
    # Use the FRDM-reported ratio if available; otherwise derive from i_ma
    ratios = [r.ratio for r in window if r.ratio is not None]
    if ratios:
        current_ratio = ratios[-1]
    else:
        # Fallback: estimate from i_ma if available, else 1.0
        i_values = [r.i_ma for r in window if r.i_ma is not None]
        i_base = [r.i_base_ma for r in window if r.i_base_ma is not None]
        if i_values and i_base:
            current_ratio = i_values[-1] / i_base[-1] if i_base[-1] > 0 else 1.0
        else:
            current_ratio = 1.0

    # ── temperature slope (C/min) ─────────────────────────────────────────────
    temps = [(r.ts, r.temp_c) for r in window]
    if len(temps) >= 2:
        xs = [t for t, _ in temps]
        ys = [v for _, v in temps]
        slope_per_s = _linear_slope(xs, ys)
        temp_slope = slope_per_s * 60.0        # convert to C/min
    else:
        temp_slope = 0.0

    # ── gas delta ─────────────────────────────────────────────────────────────
    baseline_cutoff = now - (WINDOW_S - BASELINE_S)   # i.e. now - 30 s
    baseline_readings = [r for r in readings if r.ts < baseline_cutoff]
    if baseline_readings:
        gas_base = median(r.gas_raw for r in baseline_readings)
    else:
        gas_base = median(r.gas_raw for r in window)
    gas_delta = window[-1].gas_raw - gas_base

    # ── noise spikes per minute ───────────────────────────────────────────────
    noise_total = sum(r.noise for r in window)
    window_duration = max(window[-1].ts - window[0].ts, 1.0)
    noise_per_min = (noise_total / window_duration) * 60.0

    # ── door open (any reading in window) ────────────────────────────────────
    door_open = any(r.door_open for r in window)

    # ── uptime since relay ON ─────────────────────────────────────────────────
    if relay_on_since is None:
        relay_on_since = now
    uptime_min = (now - relay_on_since) / 60.0

    return Features(
        ts=now,
        machine_id=machine_id,
        current_ratio=round(current_ratio, 3),
        temp_slope_c_per_min=round(temp_slope, 3),
        gas_delta=round(gas_delta, 1),
        noise_per_min=round(noise_per_min, 2),
        door_open=door_open,
        uptime_min=round(uptime_min, 2),
        anomaly=AnomalyLevel.NONE,
        risk=RiskLevel.LOW,
    )

