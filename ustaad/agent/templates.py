"""
agent/templates.py — memory text templates.

Exact formats:
  INCIDENT | <Machine> | <YYYY-MM-DD HH:MM> | severity: <low|medium|high>
  Signature: <signature sentence>
  Action taken by system: <text>.
  Responder: <worker id or "unassigned">.

  FIX | <Machine> | <timestamp> | by <worker>
  Root cause: <text>. Fix applied: <fix>.

  OUTCOME | <Machine> | <timestamp>
  Fix "<fix>" WORKED|FAILED. <one-sentence evidence, e.g. current back to 1.05x baseline for 10 min>.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional


def format_timestamp(dt: datetime | str) -> str:
    """Format datetime as YYYY-MM-DD HH:MM."""
    if isinstance(dt, str):
        return dt
    return dt.strftime("%Y-%m-%d %H:%M")


def build_incident_memory(
    machine_id: str,
    timestamp: datetime | str,
    severity: str,
    signature: str,
    action_taken: str,
    responder: Optional[str] = None,
) -> str:
    """Build exact INCIDENT memory block."""
    ts_str = format_timestamp(timestamp)
    resp = responder if responder else "unassigned"
    return (
        f"INCIDENT | {machine_id} | {ts_str} | severity: {severity}\n"
        f"Signature: {signature}\n"
        f"Action taken by system: {action_taken}.\n"
        f"Responder: {resp}."
    )


def build_fix_memory(
    machine_id: str,
    timestamp: datetime | str,
    worker: str,
    root_cause: str,
    fix_applied: str,
) -> str:
    """Build exact FIX memory block."""
    ts_str = format_timestamp(timestamp)
    return (
        f"FIX | {machine_id} | {ts_str} | by {worker}\n"
        f"Root cause: {root_cause}. Fix applied: {fix_applied}."
    )


def build_outcome_memory(
    machine_id: str,
    timestamp: datetime | str,
    fix: str,
    worked: bool,
    evidence: str,
) -> str:
    """Build exact OUTCOME memory block."""
    ts_str = format_timestamp(timestamp)
    outcome_str = "WORKED" if worked else "FAILED"
    return (
        f"OUTCOME | {machine_id} | {ts_str}\n"
        f"Fix \"{fix}\" {outcome_str}. {evidence}"
    )

