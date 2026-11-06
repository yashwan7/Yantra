"""
agent/memory.py — MemoryStore protocol and implementations.

Implements:
  - MemoryStore (Protocol)
  - HindsightMemory (Vectorize Hindsight client)
  - LocalMemory (JSONL token-overlap search fallback)
  - get_memory_store() factory
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Protocol

from agent.config import get_settings
from agent.models import Memory

logger = logging.getLogger(__name__)


class MemoryStore(Protocol):
    """Protocol for memory persistence, retrieval, and reflection."""

    def retain(
        self,
        text: str,
        context: Optional[str] = None,
        timestamp: Optional[datetime | str] = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, str]] = None,
    ) -> None:
        """Store a text entry into memory."""
        ...

    def recall(
        self,
        query: str,
        limit: int = 5,
        tags: Optional[list[str]] = None,
    ) -> list[Memory]:
        """Retrieve relevant past memories."""
        ...

    def reflect(self, question: str) -> str:
        """Synthesize patterns or answers across all stored memories."""
        ...


# ── LocalMemory Implementation ───────────────────────────────────────────────

def sanitize_bank_id(bank_id: str) -> str:
    """Sanitize bank ID for filesystem path safety."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", bank_id)


class LocalMemory:
    """
    JSONL-backed memory store with token-overlap similarity search.
    Used when HINDSIGHT_API_KEY is not configured or in SIMULATOR mode.
    Each memory bank maintains its own isolated JSONL store.
    """

    def __init__(self, bank_id: str = "ustaad-site1", filepath: Optional[str | Path] = None) -> None:
        self.bank_id = bank_id
        if filepath is not None:
            self.path = Path(filepath)
        else:
            clean_bank = sanitize_bank_id(bank_id)
            self.path = Path(f"data/local_memory_{clean_bank}.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        self._entries.clear()
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self._entries.append(json.loads(line))
                        except Exception:
                            pass
        logger.info("LocalMemory loaded %d entries from %s", len(self._entries), self.path)

    def _save_entry(self, entry: dict[str, Any]) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def retain(
        self,
        text: str,
        context: Optional[str] = None,
        timestamp: Optional[datetime | str] = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, str]] = None,
    ) -> None:
        ts_str = str(timestamp) if timestamp else datetime.utcnow().isoformat()
        entry_id = f"mem_{int(time.time() * 1000)}_{len(self._entries)}"
        entry = {
            "id": entry_id,
            "text": text,
            "context": context or "",
            "timestamp": ts_str,
            "tags": tags or [],
            "metadata": metadata or {},
        }
        self._entries.append(entry)
        self._save_entry(entry)
        logger.debug("LocalMemory retained entry: %s", entry_id)

    def _tokenize(self, text: str) -> set[str]:
        words = re.findall(r"\w+", text.lower())
        return set(words)

    def recall(
        self,
        query: str,
        limit: int = 5,
        tags: Optional[list[str]] = None,
    ) -> list[Memory]:
        q_tokens = self._tokenize(query)
        if not q_tokens or not self._entries:
            return []

        scored: list[tuple[float, dict[str, Any]]] = []
        for e in self._entries:
            # Check tags filter if provided
            if tags:
                e_tags = set(e.get("tags", []))
                if not any(t in e_tags for t in tags):
                    continue

            e_tokens = self._tokenize(e["text"])
            if not e_tokens:
                continue

            intersection = q_tokens & e_tokens
            # Jaccard + token overlap score
            score = len(intersection) / len(q_tokens | e_tokens) + 0.1 * len(intersection)
            if score > 0:
                scored.append((score, e))

        scored.sort(key=lambda x: x[0], reverse=True)
        results: list[Memory] = []
        for s, e in scored[:limit]:
            results.append(
                Memory(
                    id=e["id"],
                    text=e["text"],
                    score=round(s, 3),
                    tags=e.get("tags", []),
                    metadata=e.get("metadata", {}),
                )
            )
        return results

    def reflect(self, question: str) -> str:
        """Simple rule/pattern synthesizer over stored entries."""
        if not self._entries:
            return "No historical incidents recorded in memory."

        total = len(self._entries)
        incidents = [e for e in self._entries if e["text"].startswith("INCIDENT")]
        fixes = [e for e in self._entries if e["text"].startswith("FIX")]
        outcomes = [e for e in self._entries if e["text"].startswith("OUTCOME")]

        worked = sum(1 for o in outcomes if "WORKED" in o["text"])
        failed = sum(1 for o in outcomes if "FAILED" in o["text"])

        # Count most frequent fixes
        fix_counts: dict[str, int] = {}
        for f in fixes:
            m = re.search(r"Fix applied:\s*([^.\n]+)", f["text"])
            if m:
                fix_name = m.group(1).strip()
                fix_counts[fix_name] = fix_counts.get(fix_name, 0) + 1

        top_fix_str = ", ".join(f"{k} ({v}x)" for k, v in sorted(fix_counts.items(), key=lambda x: x[1], reverse=True)[:3])

        return (
            f"Synthesized from {total} memory entries ({len(incidents)} incidents, {len(fixes)} fixes, {len(outcomes)} outcomes):\n"
            f"Fix outcomes: {worked} worked, {failed} failed.\n"
            f"Most common fixes: {top_fix_str or 'none'}.\n"
            f"Recent history indicates recurrent anomalies require checking mechanical mounts if lubrication fails repeatedly."
        )


# ── HindsightMemory Implementation ───────────────────────────────────────────

class HindsightMemory:
    """
    Memory store backed by Vectorize Hindsight API client.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        bank_id: str,
    ) -> None:
        self.bank_id = bank_id
        from hindsight_client import Hindsight
        self.client = Hindsight(base_url=base_url, api_key=api_key)
        logger.info("HindsightMemory initialized for bank '%s' at %s", bank_id, base_url)

    def retain(
        self,
        text: str,
        context: Optional[str] = None,
        timestamp: Optional[datetime | str] = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, str]] = None,
    ) -> None:
        try:
            self.client.retain(
                bank_id=self.bank_id,
                content=text,
                timestamp=timestamp,
                context=context,
                tags=tags,
                metadata=metadata,
            )
            logger.info("HindsightMemory retained memory in bank '%s'", self.bank_id)
        except Exception:
            logger.exception("HindsightMemory retain error")
            raise

    def recall(
        self,
        query: str,
        limit: int = 5,
        tags: Optional[list[str]] = None,
    ) -> list[Memory]:
        try:
            resp = self.client.recall(
                bank_id=self.bank_id,
                query=query,
                tags=tags,
                max_tokens=4096,
                budget="mid",
            )
            results: list[Memory] = []
            for r in getattr(resp, "results", []):
                score = 0.0
                if hasattr(r, "scores") and isinstance(r.scores, dict):
                    score = float(r.scores.get("final_score", 0.0))
                results.append(
                    Memory(
                        id=str(r.id),
                        text=r.text or "",
                        score=round(score, 3),
                        tags=getattr(r, "tags", []) or [],
                        metadata=getattr(r, "metadata", {}) or {},
                    )
                )
            return results[:limit]
        except Exception:
            logger.exception("HindsightMemory recall error")
            return []

    def reflect(self, question: str) -> str:
        try:
            resp = self.client.reflect(
                bank_id=self.bank_id,
                query=question,
                budget="low",
            )
            return resp.text or ""
        except Exception:
            logger.exception("HindsightMemory reflect error")
            return ""


# ── Factory ───────────────────────────────────────────────────────────────────

_memory_registry: dict[str, MemoryStore] = {}


def get_memory_store(force_local: bool = False, bank_id: Optional[str] = None) -> MemoryStore:
    """Return memory store for the specified bank according to environment config."""
    global _memory_registry
    cfg = get_settings()
    target_bank = bank_id if bank_id is not None else cfg.hindsight_bank_id

    registry_key = f"{target_bank}::force_local={force_local}"
    if registry_key in _memory_registry:
        return _memory_registry[registry_key]

    if cfg.use_hindsight and not force_local:
        try:
            store = HindsightMemory(
                base_url=cfg.hindsight_base_url,
                api_key=cfg.hindsight_api_key,
                bank_id=target_bank,
            )
            _memory_registry[registry_key] = store
            return store
        except Exception:
            logger.exception("Failed to initialize Hindsight client, falling back to LocalMemory")

    store = LocalMemory(bank_id=target_bank)
    _memory_registry[registry_key] = store
    return store

