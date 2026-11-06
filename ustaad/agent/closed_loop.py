"""
agent/closed_loop.py — closed-loop incident response state machine.

State sequence:
  IDLE -> DETECTED -> ADVISED -> WAITING_FIX -> RESET -> VERIFYING -> OUTCOME
  - On WORKED: back to IDLE
  - On FAILED: back to DETECTED (escalation=True)

Injectable clock Callable[[], float] allows fast and deterministic testing.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Callable, Optional

from agent.anomaly import classify, severity_label
from agent.config import get_settings
from agent.llm import LlmAdvisor, build_template_advice
from agent.memory import get_memory_store
from agent.models import (
    AnomalyLevel,
    Features,
    Incident,
    LoopState,
    Reading,
    RiskLevel,
    ScreenType,
    UiDisplay,
    UiEvent,
    UiEventType,
)
from agent.signature import build_signature
from agent.state import SharedState, TimelineEntry
from agent.templates import (
    build_fix_memory,
    build_incident_memory,
    build_outcome_memory,
)
from agent.tools import ToolRegistry

logger = logging.getLogger(__name__)


class ClosedLoopController:
    """Controls the incident response loop."""

    def __init__(
        self,
        state: SharedState,
        clock: Optional[Callable[[], float]] = None,
        llm: Optional[Any] = None,
    ) -> None:
        self.state = state
        self.clock = clock or time.time
        self.cfg = get_settings()
        self.llm = llm or LlmAdvisor()
        self.registry = ToolRegistry(state)
        self.store = get_memory_store()

        self.current_state: LoopState = LoopState.IDLE
        self.verify_started_at: float = 0.0
        self.verify_failed_during_window: bool = False
        self.badged_worker: Optional[str] = None
        self.fix_chosen: Optional[str] = None
        self.incident_counter: int = 0

    def step(self) -> LoopState:
        """Execute one evaluation tick of the state machine."""
        now = self.clock()
        readings = self.state.get_readings()
        latest_reading = self.state.latest_reading()
        features = self.state.get_features()

        # Drain UI events from the queue
        while not self.state.ui_event_queue.empty():
            evt = self.state.ui_event_queue.get_nowait()
            self._handle_ui_event(evt)

        # ── State Machine Transitions ─────────────────────────────────────────

        if self.current_state == LoopState.IDLE:
            if features:
                if features.anomaly == AnomalyLevel.HARD:
                    self._transition_to_detected(features, latest_reading)
                elif features.anomaly == AnomalyLevel.SOFT:
                    self._handle_soft_anomaly(features)

        elif self.current_state == LoopState.DETECTED:
            self._transition_to_advised()

        elif self.current_state == LoopState.ADVISED:
            # Display has been set; now wait for on-site technician
            self.current_state = LoopState.WAITING_FIX

        elif self.current_state == LoopState.WAITING_FIX:
            # Stays here until technician badges in, selects fix, and initiates reset
            pass

        elif self.current_state == LoopState.RESET:
            # Execute reset and transition to VERIFYING
            self._execute_reset()

        elif self.current_state == LoopState.VERIFYING:
            self._check_verification(features, latest_reading, now)

        return self.current_state

    # ── State Actions ─────────────────────────────────────────────────────────

    def _transition_to_detected(
        self,
        features: Features,
        latest_reading: Optional[Reading],
        escalation: bool = False,
    ) -> None:
        now_dt = datetime.utcfromtimestamp(self.clock())
        self.incident_counter += 1
        inc_id = f"inc_{int(self.clock())}_{self.incident_counter}"
        sig = build_signature(features)
        severity = "high" if features.anomaly == AnomalyLevel.HARD else "medium"
        if escalation:
            severity = "high"

        logger.warning(
            "State -> DETECTED for %s (incident=%s, escalation=%s)",
            features.machine_id,
            inc_id,
            escalation,
        )

        incident = Incident(
            incident_id=inc_id,
            machine_id=features.machine_id,
            detected_at=now_dt,
            signature=sig,
            severity=severity,
            anomaly_level=features.anomaly,
            features=features,
            escalation=escalation,
        )
        self.state.set_incident(incident)

        # Retain INCIDENT in persistent memory
        action_text = "Overcurrent cutoff triggered, power isolated" if latest_reading and latest_reading.cutoff_event else "Hard threshold anomaly detected"
        if escalation:
            action_text = "Initial fix failed verification, anomaly re-escalated"

        inc_mem = build_incident_memory(
            machine_id=features.machine_id,
            timestamp=now_dt,
            severity=severity,
            signature=sig,
            action_taken=action_text,
            responder="unassigned",
        )
        self.store.retain(
            inc_mem,
            timestamp=now_dt,
            tags=[f"machine:{features.machine_id}", "type:incident"],
        )
        self.state.add_timeline_entry(
            TimelineEntry(kind="INCIDENT", text=inc_mem, ts=self.clock())
        )

        self.current_state = LoopState.DETECTED

    def _transition_to_advised(self) -> None:
        inc = self.state.get_incident()
        if not inc:
            self.current_state = LoopState.IDLE
            return

        logger.info("Recalling past memories for signature: %s", inc.signature)
        recalled = self.store.recall(inc.signature, limit=5)
        inc.recalled = recalled
        self.state.set_recalled(recalled)

        # Get LLM or template advice
        advice = self.llm.generate_advice(
            machine_id=inc.machine_id,
            signature=inc.signature,
            recalled=recalled,
            registry=self.registry,
            is_precursor=False,
        )
        if inc.escalation:
            advice = f"[ESCALATED WARNING] Previous fix was ineffective!\n{advice}"

        inc.advice = advice

        # Update display
        title = "ESCALATED FAULT" if inc.escalation else "CRITICAL ANOMALY"
        self.state.set_display(
            UiDisplay(
                screen=ScreenType.ALERT,
                title=title,
                body=advice,
                risk=RiskLevel.HIGH,
            )
        )

        self.current_state = LoopState.ADVISED

    def _handle_soft_anomaly(self, features: Features) -> None:
        now = self.clock()
        last_soft = self.state.get_last_soft_recall_ts()
        if now - last_soft < self.cfg.soft_recall_interval_s:
            return  # Rate-limited

        self.state.set_last_soft_recall_ts(now)
        sig = build_signature(features)
        recalled = self.store.recall(sig, limit=3)
        if recalled:
            logger.info("Soft anomaly matched historical incidents! Issuing early warning.")
            warning = build_template_advice(
                features.machine_id, sig, recalled, is_precursor=True
            )
            self.state.set_display(
                UiDisplay(
                    screen=ScreenType.ALERT,
                    title="EARLY WARNING",
                    body=warning,
                    risk=RiskLevel.MED,
                )
            )
            self.state.add_timeline_entry(
                TimelineEntry(
                    kind="INCIDENT",
                    text=f"PRECURSOR WARNING | {features.machine_id} | {sig}",
                    ts=now,
                )
            )

    def _handle_ui_event(self, evt: UiEvent) -> None:
        logger.info("Handling UI event: type=%s worker=%s fix=%s", evt.type, evt.worker, evt.fix)
        inc = self.state.get_incident()

        if evt.type == UiEventType.BADGE:
            self.badged_worker = evt.worker
            if inc:
                inc.worker_id = evt.worker
            logger.info("Worker '%s' badged in", evt.worker)
            self.state.set_display(
                UiDisplay(
                    screen=ScreenType.FIX_SELECT,
                    title=f"Worker {evt.worker}",
                    body="Select corrective action taken:",
                    risk=RiskLevel.MED,
                    worker=evt.worker,
                )
            )

        elif evt.type == UiEventType.FIX:
            if not self.badged_worker:
                logger.warning("Fix selected without worker badge")
                return
            self.fix_chosen = evt.fix
            if inc:
                inc.fix_chosen = evt.fix
                inc.fix_at = datetime.utcfromtimestamp(self.clock())

                # Retain FIX memory
                fix_mem = build_fix_memory(
                    machine_id=inc.machine_id,
                    timestamp=inc.fix_at,
                    worker=self.badged_worker,
                    root_cause=f"Anomaly: {inc.signature[:40]}...",
                    fix_applied=evt.fix or "Other",
                )
                self.store.retain(
                    fix_mem,
                    timestamp=inc.fix_at,
                    tags=[f"machine:{inc.machine_id}", f"worker:{self.badged_worker}", "type:fix"],
                )
                self.state.add_timeline_entry(
                    TimelineEntry(kind="FIX", text=fix_mem, ts=self.clock())
                )

            self.state.set_display(
                UiDisplay(
                    screen=ScreenType.BADGE,
                    title="Confirm Reset",
                    body=f"Fix '{evt.fix}' chosen. Tap badge or send RESET to power on.",
                    risk=RiskLevel.MED,
                    worker=self.badged_worker,
                )
            )

        elif evt.type == UiEventType.RESET:
            if not self.badged_worker:
                logger.warning("Reset attempted without badge")
                self.state.set_display(
                    UiDisplay(
                        screen=ScreenType.ALERT,
                        title="Reset Refused",
                        body="RFID badge required before resetting safety interlock.",
                        risk=RiskLevel.HIGH,
                    )
                )
                return

            if not self.fix_chosen:
                logger.warning("Reset attempted without selecting fix")
                self.state.set_display(
                    UiDisplay(
                        screen=ScreenType.FIX_SELECT,
                        title="Select Fix",
                        body="Select fix action before requesting reset.",
                        risk=RiskLevel.MED,
                        worker=self.badged_worker,
                    )
                )
                return

            self.current_state = LoopState.RESET

    def _execute_reset(self) -> None:
        inc = self.state.get_incident()
        worker = self.badged_worker or "W-07"
        logger.info("Executing safety relay reset by worker %s", worker)

        # In simulator mode, reset simulator
        from agent.simulator import apply_reset
        apply_reset(worker)

        self.verify_started_at = self.clock()
        self.verify_failed_during_window = False
        self.current_state = LoopState.VERIFYING
        self.state.set_display(
            UiDisplay(
                screen=ScreenType.VERIFYING,
                title="Verifying System",
                body=f"Relay engaged. Monitoring sensors for {self.cfg.verify_seconds}s...",
                risk=RiskLevel.LOW,
                worker=worker,
                countdown_s=self.cfg.verify_seconds,
            )
        )

    def _check_verification(
        self,
        features: Optional[Features],
        latest_reading: Optional[Reading],
        now: float,
    ) -> None:
        inc = self.state.get_incident()
        elapsed = now - self.verify_started_at
        remaining = max(0, int(self.cfg.verify_seconds - elapsed))

        # Update countdown on display
        self.state.set_display(
            UiDisplay(
                screen=ScreenType.VERIFYING,
                title="Verifying Fix",
                body=f"Checking telemetry stability ({remaining}s remaining)...",
                risk=RiskLevel.LOW,
                worker=self.badged_worker,
                countdown_s=remaining,
            )
        )

        # Check for abnormal readings during verification window (only for telemetry after reset)
        if latest_reading and latest_reading.ts > self.verify_started_at:
            if latest_reading.cutoff_event:
                self.verify_failed_during_window = True
        if features and features.ts > self.verify_started_at:
            # "Normal" = current_ratio < 1.15 and temp slope stable (< 1.0)
            if features.current_ratio >= 1.15 or features.temp_slope_c_per_min > 1.0:
                self.verify_failed_during_window = True

        # If verify duration complete, evaluate outcome
        if elapsed >= self.cfg.verify_seconds:
            worked = not self.verify_failed_during_window
            now_dt = datetime.utcfromtimestamp(now)
            machine_id = inc.machine_id if inc else self.cfg.machine_id
            fix = self.fix_chosen or "Inspection"

            evidence = (
                f"current ratio stayed under 1.10x for {self.cfg.verify_seconds}s"
                if worked
                else "current or temperature breached threshold within verification window"
            )

            out_mem = build_outcome_memory(
                machine_id=machine_id,
                timestamp=now_dt,
                fix=fix,
                worked=worked,
                evidence=evidence,
            )

            self.store.retain(
                out_mem,
                timestamp=now_dt,
                tags=[f"machine:{machine_id}", f"fix:{fix}", f"status:{'worked' if worked else 'failed'}"],
            )
            self.state.add_timeline_entry(
                TimelineEntry(kind="OUTCOME", text=out_mem, ts=now, worked=worked)
            )

            if worked:
                logger.info("Verification PASSED: fix '%s' WORKED", fix)
                self.state.set_display(
                    UiDisplay(
                        screen=ScreenType.RESULT,
                        title="Fix Verified",
                        body=f"Fix '{fix}' WORKED. All sensors normal. Resuming operational state.",
                        risk=RiskLevel.LOW,
                        worker=self.badged_worker,
                    )
                )
                # Clear active incident and return to IDLE
                self.state.set_incident(None)
                self.badged_worker = None
                self.fix_chosen = None
                self.current_state = LoopState.IDLE
            else:
                logger.warning("Verification FAILED: fix '%s' did not resolve anomaly", fix)
                self.state.set_display(
                    UiDisplay(
                        screen=ScreenType.RESULT,
                        title="Fix FAILED",
                        body=f"Fix '{fix}' FAILED. Escalating incident with reinforced history advice.",
                        risk=RiskLevel.HIGH,
                        worker=self.badged_worker,
                    )
                )
                # Escalate back to DETECTED
                features_now = features or self.state.get_features() or Features(
                    ts=now,
                    machine_id=machine_id,
                    current_ratio=1.5,
                    temp_slope_c_per_min=2.0,
                    gas_delta=0.0,
                    noise_per_min=0.0,
                    door_open=False,
                    uptime_min=1.0,
                )
                self._transition_to_detected(features_now, latest_reading, escalation=True)
