"""tests/test_anomaly.py — unit tests for anomaly classification thresholds."""
from __future__ import annotations

import time

import pytest

from agent.anomaly import classify, HARD_RATIO, SOFT_RATIO_LOW
from agent.models import AnomalyLevel, Features, Reading, RiskLevel


def _features(**kwargs) -> Features:
    defaults = dict(
        ts=time.time(),
        machine_id="Pump-2",
        current_ratio=1.0,
        temp_slope_c_per_min=0.0,
        gas_delta=0.0,
        noise_per_min=0.0,
        door_open=False,
        uptime_min=5.0,
        anomaly=AnomalyLevel.NONE,
        risk=RiskLevel.LOW,
    )
    defaults.update(kwargs)
    return Features(**defaults)


def _cutoff_reading() -> Reading:
    return Reading(
        ts=time.time(), temp_c=30.0, hum=52.0, gas_raw=410, noise=0,
        ldr_raw=2300, door_open=False, i_ma=720.0, i_base_ma=380.0,
        ratio=1.89, relay="OFF", cutoff_event=True, cutoff_reason="OVERCURRENT",
        source="test",
    )


class TestHardAnomaly:
    def test_ratio_hard(self):
        f = _features(current_ratio=1.5)
        result = classify(f)
        assert result.anomaly == AnomalyLevel.HARD

    def test_ratio_just_above_hard(self):
        f = _features(current_ratio=HARD_RATIO + 0.01)
        assert classify(f).anomaly == AnomalyLevel.HARD

    def test_ratio_at_hard_boundary_not_triggered(self):
        # exactly 1.4 is NOT hard (strict >)
        f = _features(current_ratio=1.4)
        result = classify(f)
        assert result.anomaly != AnomalyLevel.HARD

    def test_temp_slope_hard(self):
        f = _features(temp_slope_c_per_min=3.5)
        assert classify(f).anomaly == AnomalyLevel.HARD

    def test_gas_delta_hard(self):
        f = _features(gas_delta=350.0)
        assert classify(f).anomaly == AnomalyLevel.HARD

    def test_noise_hard(self):
        f = _features(noise_per_min=9.0)
        assert classify(f).anomaly == AnomalyLevel.HARD

    def test_cutoff_event_hard(self):
        f = _features(current_ratio=1.0)   # ratio looks normal
        result = classify(f, _cutoff_reading())
        assert result.anomaly == AnomalyLevel.HARD
        assert result.risk == RiskLevel.HIGH

    def test_hard_sets_risk_high(self):
        f = _features(current_ratio=1.5)
        assert classify(f).risk == RiskLevel.HIGH


class TestSoftAnomaly:
    def test_two_weak_signals(self):
        f = _features(current_ratio=1.2, noise_per_min=4.0)
        result = classify(f)
        assert result.anomaly == AnomalyLevel.SOFT
        assert result.risk == RiskLevel.MED

    def test_one_weak_signal_no_anomaly(self):
        f = _features(current_ratio=1.2)
        assert classify(f).anomaly == AnomalyLevel.NONE

    def test_ratio_and_temp_slope_soft(self):
        f = _features(current_ratio=1.25, temp_slope_c_per_min=1.5)
        assert classify(f).anomaly == AnomalyLevel.SOFT

    def test_all_four_weak_signals(self):
        f = _features(
            current_ratio=1.25,
            temp_slope_c_per_min=2.0,
            noise_per_min=5.0,
            gas_delta=150.0,
        )
        assert classify(f).anomaly == AnomalyLevel.SOFT


class TestNoneAnomaly:
    def test_normal_conditions(self):
        f = _features()
        assert classify(f).anomaly == AnomalyLevel.NONE
        assert classify(f).risk == RiskLevel.LOW

    def test_slightly_elevated_ratio_below_soft(self):
        f = _features(current_ratio=1.1)   # below 1.15 soft threshold
        assert classify(f).anomaly == AnomalyLevel.NONE

