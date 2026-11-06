"""tests/test_signature.py — tests for deterministic signature builder."""
from __future__ import annotations

import pytest

from agent.models import AnomalyLevel, Features, RiskLevel
from agent.signature import build_signature


def _make_feat(
    machine_id: str = "Pump-2",
    ratio: float = 1.0,
    temp_slope: float = 0.0,
    gas_delta: float = 0.0,
    noise_per_min: float = 0.0,
    door_open: bool = False,
    uptime_min: float = 10.0,
) -> Features:
    return Features(
        ts=1730900000.0,
        machine_id=machine_id,
        current_ratio=ratio,
        temp_slope_c_per_min=temp_slope,
        gas_delta=gas_delta,
        noise_per_min=noise_per_min,
        door_open=door_open,
        uptime_min=uptime_min,
        anomaly=AnomalyLevel.NONE,
        risk=RiskLevel.LOW,
    )


def test_signature_exact_format_and_determinism():
    f = _make_feat(
        machine_id="Pump-2",
        ratio=1.24,
        temp_slope=1.52,
        gas_delta=50.0,
        noise_per_min=3.0,
        door_open=False,
        uptime_min=5.4,
    )
    sig1 = build_signature(f)
    sig2 = build_signature(f)

    assert sig1 == sig2
    expected = (
        "Pump-2: current 1.2x baseline, temperature rising (+1.5 C/min), "
        "gas normal, 3 noise spikes/min, panel closed, 5 min after startup."
    )
    assert sig1 == expected


def test_signature_buckets():
    # temperature stable (slope <= 1.0), gas elevated (> 150), panel open
    f = _make_feat(
        machine_id="Fan-1",
        ratio=1.58,
        temp_slope=0.8,
        gas_delta=200.0,
        noise_per_min=7.8,
        door_open=True,
        uptime_min=45.0,
    )
    sig = build_signature(f)
    expected = (
        "Fan-1: current 1.6x baseline, temperature stable (+0.8 C/min), "
        "gas elevated, 8 noise spikes/min, panel open, 45 min after startup."
    )
    assert sig == expected

