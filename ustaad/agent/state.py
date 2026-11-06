"""
agent/state.py — thread-safe shared state for the agent.

All fields are accessed from multiple threads (ingest, closed_loop, dashboard).
Uses threading.Lock for mutation-heavy lists and queue.Queue for events.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from queue import Queue
from typing import Deque, Optional

from agent.models import (
    Features,
    Incident,
    Memory,
    Reading,
    UiDisplay,
    UiEvent,
)


@dataclass
class TimelineEntry:
    """A single entry in the persistent memory timeline shown in the dashboard."""
    kind: str           # "INCIDENT" | "FIX" | "OUTCOME"
    text: str
    ts: float
    worked: Optional[bool] = None   # True/False for OUTCOME, None otherwise


class SharedState:
    """
    Thread-safe shared state.

    Use the accessor methods rather than touching the internal fields directly.
    """

    def __init__(self, maxlen: int = 300) -> None:
        self._lock = threading.Lock()

        # Rolling buffer of the latest normalised readings
        self._readings: Deque[Reading] = deque(maxlen=maxlen)

        # Latest computed features
        self._latest_features: Optional[Features] = None

        # Active incident (None when IDLE)
        self._active_incident: Optional[Incident] = None

        # Recalled memories for the current incident
        self._recalled: list[Memory] = []

        # Persistent timeline of INCIDENT / FIX / OUTCOME entries
        self._timeline: Deque[TimelineEntry] = deque(maxlen=500)

        # Last Hindsight reflect output
        self._patterns: str = ""

        # Current display payload
        self._display: UiDisplay = UiDisplay()

        # Ui-event queue (Uno Q → closed_loop)
        self.ui_event_queue: Queue[UiEvent] = Queue()

        # Simulator scenario control
        self._sim_scenario: Optional[str] = None

        # Soft-recall last fired timestamp
        self._last_soft_recall_ts: float = 0.0

    # ── readings ──────────────────────────────────────────────────────────────

    def push_reading(self, r: Reading) -> None:
        with self._lock:
            self._readings.append(r)

    def get_readings(self) -> list[Reading]:
        with self._lock:
            return list(self._readings)

    def latest_reading(self) -> Optional[Reading]:
        with self._lock:
            return self._readings[-1] if self._readings else None

    # ── features ──────────────────────────────────────────────────────────────

    def set_features(self, f: Features) -> None:
        with self._lock:
            self._latest_features = f

    def get_features(self) -> Optional[Features]:
        with self._lock:
            return self._latest_features

    # ── incident ──────────────────────────────────────────────────────────────

    def set_incident(self, inc: Optional[Incident]) -> None:
        with self._lock:
            self._active_incident = inc

    def get_incident(self) -> Optional[Incident]:
        with self._lock:
            return self._active_incident

    # ── recalled memories ─────────────────────────────────────────────────────

    def set_recalled(self, memories: list[Memory]) -> None:
        with self._lock:
            self._recalled = list(memories)

    def get_recalled(self) -> list[Memory]:
        with self._lock:
            return list(self._recalled)

    # ── timeline ──────────────────────────────────────────────────────────────

    def add_timeline_entry(self, entry: TimelineEntry) -> None:
        with self._lock:
            self._timeline.append(entry)

    def get_timeline(self) -> list[TimelineEntry]:
        with self._lock:
            return list(self._timeline)

    # ── patterns (reflect output) ─────────────────────────────────────────────

    def set_patterns(self, text: str) -> None:
        with self._lock:
            self._patterns = text

    def get_patterns(self) -> str:
        with self._lock:
            return self._patterns

    # ── display ───────────────────────────────────────────────────────────────

    def set_display(self, d: UiDisplay) -> None:
        with self._lock:
            self._display = d

    def get_display(self) -> UiDisplay:
        with self._lock:
            return self._display

    # ── simulator scenario ────────────────────────────────────────────────────

    def set_scenario(self, name: Optional[str]) -> None:
        with self._lock:
            self._sim_scenario = name

    def get_scenario(self) -> Optional[str]:
        with self._lock:
            return self._sim_scenario

    # ── soft-recall timing ────────────────────────────────────────────────────

    def get_last_soft_recall_ts(self) -> float:
        with self._lock:
            return self._last_soft_recall_ts

    def set_last_soft_recall_ts(self, ts: float) -> None:
        with self._lock:
            self._last_soft_recall_ts = ts

