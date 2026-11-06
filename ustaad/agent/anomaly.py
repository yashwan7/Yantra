"""
agent/anomaly.py — deterministic anomaly classification.

HARD anomaly (immediate response required):
  - current_ratio > 1.4
  - temp_slope_c_per_min > 3.0
  - gas_delta > 300
  - noise_per_min > 8
  - a CUTOFF event in the latest reading

SOFT anomaly (precursor warning):
  At least 2 of:
  - 1.15 <= current_ratio <= 1.4
  - 1.0  <= temp_slope <= 3.0
  - 3    <= noise_per_min <= 8
  - 100  <= gas_delta <= 300

No LLM or probabilistic logic here — pure threshold comparison.
"""
from __future__ import annotations

import logging

from agent.models import AnomalyLevel, Features, Reading, RiskLevel

logger = logging.getLogger(__name__)

# ── Hard thresholds ───────────────────────────────────────────────────────────
HARD_RATIO: float = 1.4
HARD_TEMP_SLOPE: float = 3.0
HARD_GAS_DELTA: float = 300.0
HARD_NOISE: float = 8.0

# ── Soft thresholds (weak signals) ────────────────────────────────────────────
SOFT_RATIO_LOW: float = 1.15
SOFT_RATIO_HIGH: float = 1.4
SOFT_TEMP_LOW: float = 1.0
SOFT_TEMP_HIGH: float = 3.0
SOFT_NOISE_LOW: float = 3.0
SOFT_NOISE_HIGH: float = 8.0
SOFT_GAS_LOW: float = 100.0
SOFT_GAS_HIGH: float = 300.0
SOFT_SIGNAL_COUNT: int = 2   # need at least this many weak signals


def classify(features: Features, latest_reading: Reading | None = None) -> Features:
    """
    Classify features and return a new Features instance with anomaly and risk set.

    latest_reading is checked for a CUTOFF event (hard anomaly trigger).
    """
    # Check CUTOFF event first
    if latest_reading and latest_reading.cutoff_event:
        logger.warning(
            "HARD anomaly: CUTOFF event detected on %s (reason=%s)",
            features.machine_id,
            latest_reading.cutoff_reason,
        )
        return _make(features, AnomalyLevel.HARD, RiskLevel.HIGH)

    # Hard conditions
    hard_triggers: list[str] = []
    if features.current_ratio > HARD_RATIO:
        hard_triggers.append(f"ratio={features.current_ratio:.2f}")
    if features.temp_slope_c_per_min > HARD_TEMP_SLOPE:
        hard_triggers.append(f"temp_slope={features.temp_slope_c_per_min:.1f}")
    if features.gas_delta > HARD_GAS_DELTA:
        hard_triggers.append(f"gas_delta={features.gas_delta:.0f}")
    if features.noise_per_min > HARD_NOISE:
        hard_triggers.append(f"noise={features.noise_per_min:.1f}/min")

    if hard_triggers:
        logger.warning("HARD anomaly on %s: %s", features.machine_id, ", ".join(hard_triggers))
        return _make(features, AnomalyLevel.HARD, RiskLevel.HIGH)

    # Soft conditions (weak signals)
    soft_hits: list[str] = []
    if SOFT_RATIO_LOW <= features.current_ratio <= SOFT_RATIO_HIGH:
        soft_hits.append(f"ratio={features.current_ratio:.2f}")
    if SOFT_TEMP_LOW <= features.temp_slope_c_per_min <= SOFT_TEMP_HIGH:
        soft_hits.append(f"temp_slope={features.temp_slope_c_per_min:.1f}")
    if SOFT_NOISE_LOW <= features.noise_per_min <= SOFT_NOISE_HIGH:
        soft_hits.append(f"noise={features.noise_per_min:.1f}/min")
    if SOFT_GAS_LOW <= features.gas_delta <= SOFT_GAS_HIGH:
        soft_hits.append(f"gas_delta={features.gas_delta:.0f}")

    if len(soft_hits) >= SOFT_SIGNAL_COUNT:
        logger.info("SOFT anomaly on %s: %s", features.machine_id, ", ".join(soft_hits))
        risk = RiskLevel.MED
        return _make(features, AnomalyLevel.SOFT, risk)

    return _make(features, AnomalyLevel.NONE, RiskLevel.LOW)


def _make(f: Features, anomaly: AnomalyLevel, risk: RiskLevel) -> Features:
    from dataclasses import replace
    return replace(f, anomaly=anomaly, risk=risk)


def severity_label(anomaly: AnomalyLevel) -> str:
    """Human-readable severity for memory templates."""
    return {
        AnomalyLevel.NONE: "low",
        AnomalyLevel.SOFT: "medium",
        AnomalyLevel.HARD: "high",
    }[anomaly]

