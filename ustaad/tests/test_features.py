"""tests/test_features.py — unit tests for feature computation math."""
from __future__ import annotations

import time

import pytest

from agent.features import _linear_slope, compute_features, WINDOW_S
from agent.models import Reading


def _r(ts: float, temp: float = 30.0, gas: int = 410, noise: int = 0,
        i_ma: float = 380.0, i_base: float = 380.0,
        door: bool = False) -> Reading:
    return Reading(
        ts=ts, temp_c=temp, hum=52.0, gas_raw=gas, noise=noise,
        ldr_raw=2300, door_open=door,
        i_ma=i_ma, i_base_ma=i_base, ratio=round(i_ma / i_base, 3),
        relay="ON", source="test",
    )


class TestLinearSlope:
    def test_flat(self):
        xs = [0.0, 1.0, 2.0]
        ys = [5.0, 5.0, 5.0]
        assert _linear_slope(xs, ys) == pytest.approx(0.0, abs=1e-6)

    def test_rising(self):
        xs = [0.0, 1.0, 2.0]
        ys = [0.0, 1.0, 2.0]
        assert _linear_slope(xs, ys) == pytest.approx(1.0, abs=1e-6)

    def test_falling(self):
        xs = [0.0, 1.0, 2.0, 3.0]
        ys = [30.0, 29.0, 28.0, 27.0]
        assert _linear_slope(xs, ys) == pytest.approx(-1.0, abs=1e-6)

    def test_single_point(self):
        assert _linear_slope([1.0], [5.0]) == pytest.approx(0.0)

    def test_empty(self):
        assert _linear_slope([], []) == pytest.approx(0.0)


class TestComputeFeatures:
    def _make_readings(self, n: int = 30, temp_per_tick: float = 0.0,
                       gas: int = 410, noise_every: int = 0,
                       i_ma: float = 380.0) -> list[Reading]:
        base_ts = time.time() - n * 2
        readings = []
        for i in range(n):
            ts = base_ts + i * 2
            readings.append(_r(
                ts=ts,
                temp=30.0 + i * temp_per_tick,
                gas=gas,
                noise=1 if (noise_every and i % noise_every == 0) else 0,
                i_ma=i_ma,
            ))
        return readings

    def test_returns_none_too_few(self):
        result = compute_features([_r(ts=time.time())], "Pump-2")
        assert result is None

    def test_normal_baseline(self):
        readings = self._make_readings(30)
        f = compute_features(readings, "Pump-2")
        assert f is not None
        assert f.current_ratio == pytest.approx(1.0, abs=0.01)
        assert abs(f.temp_slope_c_per_min) < 0.1   # flat
        assert f.gas_delta == pytest.approx(0.0, abs=20.0)

    def test_temp_slope_rising(self):
        # +0.1 C every 2 s = +3.0 C/min
        readings = self._make_readings(30, temp_per_tick=0.1)
        f = compute_features(readings, "Pump-2")
        assert f is not None
        # slope should be ~3 C/min (0.1/2s * 60)
        assert f.temp_slope_c_per_min == pytest.approx(3.0, abs=0.5)

    def test_current_ratio_elevated(self):
        readings = self._make_readings(30, i_ma=570.0)   # 1.5×
        f = compute_features(readings, "Pump-2")
        assert f is not None
        assert f.current_ratio == pytest.approx(1.5, abs=0.02)

    def test_noise_per_min(self):
        # noise spike every 2nd tick in a 30-tick window (15 spikes in 60 s)
        readings = self._make_readings(30, noise_every=2)
        f = compute_features(readings, "Pump-2")
        assert f is not None
        assert f.noise_per_min > 10.0   # should be ~15/min

    def test_door_open_propagates(self):
        readings = self._make_readings(5)
        readings[-1] = _r(ts=readings[-1].ts, door=True)
        f = compute_features(readings, "Pump-2")
        assert f is not None
        assert f.door_open is True

    def test_machine_id_preserved(self):
        readings = self._make_readings(5)
        f = compute_features(readings, "Fan-1")
        assert f is not None
        assert f.machine_id == "Fan-1"

