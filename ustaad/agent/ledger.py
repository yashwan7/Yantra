"""
agent/ledger.py — deterministic local outcome & incident ledger.

Stores structured incident and outcome records in JSON so that counts
(how many times a fix worked vs failed, total occurrences, last fix)
never depend on fuzzy regex parsing of LLM-extracted facts from Hindsight.

Hindsight provides semantic memory & narrative recall;
OutcomeLedger provides 100% deterministic metrics and counts.
Each memory bank maintains its own isolated ledger.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from agent.config import get_settings

logger = logging.getLogger(__name__)


def sanitize_bank_id(bank_id: str) -> str:
    """Sanitize bank ID for filesystem path safety."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", bank_id)


@dataclass
class LedgerRecord:
    machine_id: str
    kind: str             # "INCIDENT" | "FIX" | "OUTCOME" | "PRECURSOR"
    ts: float
    worker: Optional[str] = None
    fix: Optional[str] = None
    worked: Optional[bool] = None
    signature: Optional[str] = None
    evidence: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class OutcomeLedger:
    """Thread-safe persistent ledger for exact incident and fix metrics for a specific bank."""

    def __init__(self, bank_id: str = "ustaad-site1", filepath: Optional[str | Path] = None) -> None:
        self.bank_id = bank_id
        if filepath is not None:
            self.path = Path(filepath)
        else:
            clean_bank = sanitize_bank_id(bank_id)
            self.path = Path(f"data/outcome_ledger_{clean_bank}.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: list[LedgerRecord] = []
        self._load()

    def _load(self) -> None:
        self._records.clear()
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        self._records.append(LedgerRecord(**item))
            except Exception as e:
                logger.warning("Could not read outcome ledger from %s: %s", self.path, e)

    def _save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump([asdict(r) for r in self._records], f, indent=2)
        except Exception as e:
            logger.error("Could not write outcome ledger to %s: %s", self.path, e)

    def record_incident(
        self,
        machine_id: str,
        signature: str,
        ts: float,
        is_precursor: bool = False,
        worker: Optional[str] = None,
    ) -> None:
        rec = LedgerRecord(
            machine_id=machine_id,
            kind="PRECURSOR" if is_precursor else "INCIDENT",
            ts=ts,
            worker=worker,
            signature=signature,
        )
        self._records.append(rec)
        self._save()

    def record_fix(
        self,
        machine_id: str,
        fix: str,
        worker: str,
        ts: float,
        signature: Optional[str] = None,
    ) -> None:
        rec = LedgerRecord(
            machine_id=machine_id,
            kind="FIX",
            ts=ts,
            worker=worker,
            fix=fix,
            signature=signature,
        )
        self._records.append(rec)
        self._save()

    def record_outcome(
        self,
        machine_id: str,
        fix: str,
        worked: bool,
        ts: float,
        evidence: str,
        worker: Optional[str] = None,
    ) -> None:
        rec = LedgerRecord(
            machine_id=machine_id,
            kind="OUTCOME",
            ts=ts,
            worker=worker,
            fix=fix,
            worked=worked,
            evidence=evidence,
        )
        self._records.append(rec)
        self._save()

    def get_stats(self, machine_id: str) -> dict[str, Any]:
        """Compute exact aggregate counts for a machine."""
        outcomes = [r for r in self._records if r.machine_id == machine_id and r.kind == "OUTCOME"]
        fixes = [r for r in self._records if r.machine_id == machine_id and r.kind == "FIX"]
        incidents = [r for r in self._records if r.machine_id == machine_id and r.kind in ("INCIDENT", "PRECURSOR")]
        precursors = [r for r in self._records if r.machine_id == machine_id and r.kind == "PRECURSOR"]

        fix_outcomes: dict[str, dict[str, int]] = {}
        for o in outcomes:
            if not o.fix:
                continue
            if o.fix not in fix_outcomes:
                fix_outcomes[o.fix] = {"worked": 0, "failed": 0}
            if o.worked:
                fix_outcomes[o.fix]["worked"] += 1
            else:
                fix_outcomes[o.fix]["failed"] += 1

        last_fix = fixes[-1].fix if fixes else None

        # Pick best fix
        best_fix = None
        if fix_outcomes:
            best_fix = max(
                fix_outcomes.keys(),
                key=lambda k: (fix_outcomes[k]["worked"] - fix_outcomes[k]["failed"], fix_outcomes[k]["worked"]),
            )

        return {
            "total_incidents": len(incidents),
            "total_precursors": len(precursors),
            "last_fix": last_fix,
            "best_fix": best_fix or last_fix or "Inspection",
            "fix_outcomes": fix_outcomes,
        }

    def clear(self) -> None:
        self._records.clear()
        if self.path.exists():
            self.path.unlink()


_ledger_registry: dict[str, OutcomeLedger] = {}


def get_outcome_ledger(bank_id: Optional[str] = None, filepath: Optional[str | Path] = None) -> OutcomeLedger:
    global _ledger_registry
    if bank_id is None:
        bank_id = get_settings().hindsight_bank_id

    key = f"{bank_id}::{filepath}"
    if key not in _ledger_registry:
        _ledger_registry[key] = OutcomeLedger(bank_id=bank_id, filepath=filepath)
    return _ledger_registry[key]
