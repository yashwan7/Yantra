"""tests/test_closed_loop.py — unit tests for closed-loop state machine with fake clock."""
from __future__ import annotations

import time
from pathlib import Path

from agent.closed_loop import ClosedLoopController
from agent.llm import MockLLM
from agent.memory import LocalMemory
from agent.models import (
    AnomalyLevel,
    Features,
    LoopState,
    Reading,
    RiskLevel,
    ScreenType,
    UiEvent,
    UiEventType,
)
from agent.state import SharedState


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.current_time = start

    def __call__(self) -> float:
        return self.current_time

    def advance(self, seconds: float) -> None:
        self.current_time += seconds


def _normal_features(clock_time: float) -> Features:
    return Features(
        ts=clock_time,
        machine_id="Pump-2",
        current_ratio=1.02,
        temp_slope_c_per_min=0.1,
        gas_delta=0.0,
        noise_per_min=0.5,
        door_open=False,
        uptime_min=10.0,
        anomaly=AnomalyLevel.NONE,
        risk=RiskLevel.LOW,
    )


def _hard_anomaly_features(clock_time: float) -> Features:
    return Features(
        ts=clock_time,
        machine_id="Pump-2",
        current_ratio=1.85,
        temp_slope_c_per_min=2.5,
        gas_delta=50.0,
        noise_per_min=9.0,
        door_open=False,
        uptime_min=12.0,
        anomaly=AnomalyLevel.HARD,
        risk=RiskLevel.HIGH,
    )


def test_closed_loop_worked_path(tmp_path: Path):
    clock = FakeClock(1000.0)
    state = SharedState()
    mem_file = tmp_path / "closed_loop_mem.jsonl"
    mock_store = LocalMemory(filepath=mem_file)

    controller = ClosedLoopController(state, clock=clock, llm=MockLLM("Advice: Lubricate bearings"))
    controller.store = mock_store
    controller.cfg.verify_seconds = 10  # short verify for test

    # 1. Initially IDLE
    state.set_features(_normal_features(clock()))
    assert controller.step() == LoopState.IDLE

    # 2. Hard anomaly occurs
    state.set_features(_hard_anomaly_features(clock()))
    state.push_reading(
        Reading(
            ts=clock(), temp_c=35.0, hum=50.0, gas_raw=410, noise=5,
            ldr_raw=2300, door_open=False, i_ma=700.0, i_base_ma=380.0,
            ratio=1.85, relay="OFF", cutoff_event=True, cutoff_reason="OVERCURRENT",
        )
    )

    # Step -> transitions to DETECTED then ADVISED then WAITING_FIX
    controller.step()
    controller.step()
    controller.step()
    assert controller.current_state == LoopState.WAITING_FIX
    assert state.get_display().screen == ScreenType.ALERT

    # 3. Worker badges in
    state.ui_event_queue.put(UiEvent(type=UiEventType.BADGE, worker="W-07"))
    controller.step()
    assert state.get_display().screen == ScreenType.FIX_SELECT
    assert controller.badged_worker == "W-07"

    # 4. Worker selects fix
    state.ui_event_queue.put(UiEvent(type=UiEventType.FIX, fix="Lubricated"))
    controller.step()
    assert state.get_display().screen == ScreenType.BADGE
    assert controller.fix_chosen == "Lubricated"

    # 5. Worker taps reset
    state.ui_event_queue.put(UiEvent(type=UiEventType.RESET))
    controller.step()
    assert controller.current_state == LoopState.VERIFYING
    assert state.get_display().screen == ScreenType.VERIFYING

    # 6. Advance clock through verification with normal telemetry
    for _ in range(5):
        clock.advance(2.0)
        state.set_features(_normal_features(clock()))
        controller.step()

    # Clock has advanced 10 seconds -> verification finishes WORKED
    clock.advance(1.0)
    state.set_features(_normal_features(clock()))
    controller.step()

    assert controller.current_state == LoopState.IDLE
    assert state.get_incident() is None
    timeline = state.get_timeline()
    outcomes = [t for t in timeline if t.kind == "OUTCOME"]
    assert len(outcomes) == 1
    assert outcomes[0].worked is True


def test_closed_loop_failed_path(tmp_path: Path):
    clock = FakeClock(2000.0)
    state = SharedState()
    mem_file = tmp_path / "closed_loop_fail.jsonl"
    mock_store = LocalMemory(filepath=mem_file)

    controller = ClosedLoopController(state, clock=clock, llm=MockLLM("Advice: Lubricate bearings"))
    controller.store = mock_store
    controller.cfg.verify_seconds = 10

    # Trigger anomaly
    state.set_features(_hard_anomaly_features(clock()))
    controller.step()  # to DETECTED
    controller.step()  # to ADVISED
    controller.step()  # to WAITING_FIX

    # Badge + fix + reset
    state.ui_event_queue.put(UiEvent(type=UiEventType.BADGE, worker="W-07"))
    state.ui_event_queue.put(UiEvent(type=UiEventType.FIX, fix="Lubricated"))
    state.ui_event_queue.put(UiEvent(type=UiEventType.RESET))
    controller.step()

    assert controller.current_state == LoopState.VERIFYING

    # Anomaly re-occurs during verification!
    clock.advance(4.0)
    state.set_features(_hard_anomaly_features(clock()))
    controller.step()

    # Verification duration completes
    clock.advance(7.0)
    controller.step()

    # Should escalate!
    inc = state.get_incident()
    assert inc is not None
    assert inc.escalation is True
    assert controller.current_state in (LoopState.DETECTED, LoopState.ADVISED, LoopState.WAITING_FIX)


def test_closed_loop_badge_missing_refuses_reset():
    clock = FakeClock(3000.0)
    state = SharedState()
    controller = ClosedLoopController(state, clock=clock, llm=MockLLM())

    state.set_features(_hard_anomaly_features(clock()))
    controller.step()
    controller.step()
    controller.step()
    assert controller.current_state == LoopState.WAITING_FIX

    # Attempt RESET directly without badge
    state.ui_event_queue.put(UiEvent(type=UiEventType.RESET))
    controller.step()

    # Must refuse!
    assert controller.current_state == LoopState.WAITING_FIX
    assert state.get_display().title == "Reset Refused"
