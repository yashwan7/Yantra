"""
agent/signature.py — deterministic signature sentence builder.

EXACT format:
"<Machine>: current <ratio:.1f>x baseline, temperature <rising|stable> (<slope:+.1f> C/min), gas <elevated|normal>, <n> noise spikes/min, panel <open|closed>, <uptime:.0f> min after startup."

Buckets:
  temperature rising if slope > 1.0, otherwise stable
  gas elevated if gas_delta > 150, otherwise normal
"""
from __future__ import annotations

from agent.models import Features


def build_signature(features: Features) -> str:
    """Build deterministic signature string from features."""
    temp_bucket = "rising" if features.temp_slope_c_per_min > 1.0 else "stable"
    gas_bucket = "elevated" if features.gas_delta > 150.0 else "normal"
    panel_bucket = "open" if features.door_open else "closed"

    return (
        f"{features.machine_id}: current {features.current_ratio:.1f}x baseline, "
        f"temperature {temp_bucket} ({features.temp_slope_c_per_min:+.1f} C/min), "
        f"gas {gas_bucket}, {round(features.noise_per_min)} noise spikes/min, "
        f"panel {panel_bucket}, {features.uptime_min:.0f} min after startup."
    )

