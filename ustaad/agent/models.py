"""
agent/models.py — dataclasses for all inter-module messages.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ── Enumerations ──────────────────────────────────────────────────────────────

class AnomalyLevel(str, Enum):
    NONE = "NONE"
    SOFT = "SOFT"
    HARD = "HARD"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MED = "MED"
    HIGH = "HIGH"


class ScreenType(str, Enum):
    IDLE = "idle"
    ALERT = "alert"
    BADGE = "badge"
    FIX_SELECT = "fix_select"
    VERIFYING = "verifying"
    RESULT = "result"


class UiEventType(str, Enum):
    BADGE = "badge"
    FIX = "fix"
    RESET = "reset"


class LoopState(str, Enum):
    IDLE = "IDLE"
    DETECTED = "DETECTED"
    ADVISED = "ADVISED"
    WAITING_FIX = "WAITING_FIX"
    RESET = "RESET"
    VERIFYING = "VERIFYING"
    OUTCOME = "OUTCOME"


# ── Fix options ───────────────────────────────────────────────────────────────

FIX_OPTIONS: list[str] = [
    "Lubricated",
    "Cleared blockage",
    "Replaced part",
    "Tightened mount",
    "Other",
]


# ── Core dataclasses ──────────────────────────────────────────────────────────

@dataclass
class Reading:
    """Normalised sensor reading — one row every 2 seconds."""
    ts: float                    # Unix timestamp
    temp_c: float                # Temperature in Celsius
    hum: float                   # Humidity %
    gas_raw: int                 # MQ gas sensor ADC raw counts
    noise: int                   # Digital spike flag count (not audio)
    ldr_raw: int                 # LDR ADC raw (door detection)
    door_open: bool              # True when enclosure door is open
    # FRDM serial fields (may be absent until FRDM syncs)
    i_ma: Optional[float] = None           # Current in mA
    i_base_ma: Optional[float] = None      # Baseline current in mA
    ratio: Optional[float] = None          # i_ma / i_base_ma
    relay: Optional[str] = None            # "ON" or "OFF"
    # Synthetic CUTOFF event from FRDM
    cutoff_event: bool = False
    cutoff_reason: Optional[str] = None
    source: str = "sim"                    # "sim" | "mqtt" | "serial"


@dataclass
class Features:
    """Computed features over a 60-second rolling window."""
    ts: float
    machine_id: str
    current_ratio: float          # latest i_ma / baseline (1.0 = normal)
    temp_slope_c_per_min: float   # linear regression over 60-s window
    gas_delta: float              # gas_raw - median of first-30s baseline
    noise_per_min: float          # spike count in last 60 s, extrapolated to /min
    door_open: bool
    uptime_min: float             # minutes since relay ON
    anomaly: AnomalyLevel = AnomalyLevel.NONE
    risk: RiskLevel = RiskLevel.LOW


@dataclass
class Memory:
    """A single recalled memory item."""
    id: str
    text: str
    score: float = 0.0
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class Incident:
    """A live incident record (in-memory, not persisted until OUTCOME)."""
    incident_id: str
    machine_id: str
    detected_at: datetime
    signature: str
    severity: str                 # low | medium | high
    anomaly_level: AnomalyLevel
    features: Features
    recalled: list[Memory] = field(default_factory=list)
    advice: str = ""
    worker_id: Optional[str] = None
    fix_chosen: Optional[str] = None
    fix_at: Optional[datetime] = None
    outcome: Optional[str] = None      # WORKED | FAILED
    outcome_at: Optional[datetime] = None
    escalation: bool = False


@dataclass
class UiEvent:
    """An event from the Uno Q operator panel."""
    type: UiEventType
    worker: Optional[str] = None    # for BADGE events
    fix: Optional[str] = None       # for FIX events
    ts: float = field(default_factory=lambda: __import__("time").time())


@dataclass
class UiDisplay:
    """What to show on the hardware display / virtual TFT."""
    screen: ScreenType = ScreenType.IDLE
    title: str = ""
    body: str = ""
    risk: RiskLevel = RiskLevel.LOW
    worker: Optional[str] = None
    countdown_s: Optional[int] = None   # for VERIFYING screen

