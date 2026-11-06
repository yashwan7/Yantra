"""
Hindsight smoke test.

Verifies the installed Hindsight client's retain / recall / reflect API
by inspecting signatures offline (no network required).

If HINDSIGHT_API_KEY and HINDSIGHT_BASE_URL are present in .env, also performs
a live round-trip: retain → recall → reflect.

Package: hindsight-client  (pip install hindsight-client)
Import:  from hindsight_client import Hindsight

VERIFIED SIGNATURES (Phase 0, offline inspect):
  Hindsight(base_url: str, api_key: str | None = None, timeout: float = 300.0, ...)

  retain(self, bank_id: str, content: str | list[dict], timestamp=None,
         context: str | None = None, document_id=None, metadata=None,
         tags: list[str] | None = None, ...) -> RetainResponse
         RetainResponse.success: bool

  recall(self, bank_id: str, query: str, types=None, max_tokens=4096,
         budget="mid", trace=False, tags=None, ...) -> RecallResponse
         RecallResponse.results: list[RecallResult]
         RecallResult fields: id, text, type, context, metadata, tags, scores, ...

  reflect(self, bank_id: str, query: str, budget="low", context=None,
          max_tokens=None, ...) -> ReflectResponse
          ReflectResponse.text: str

  Async variants: aretain, arecall, areflect

Exit codes:
  0  — offline inspection succeeded; live test passed or skipped (no key)
  1  — live round-trip failed (key present but call failed)
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hindsight_smoke_test")

# ── load .env if present ─────────────────────────────────────────────────────
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_path)

# ── attempt import ───────────────────────────────────────────────────────────
try:
    from hindsight_client import Hindsight  # type: ignore[import]
    _have_package = True
except ImportError:
    _have_package = False
    Hindsight = None  # type: ignore[assignment]


def _inspect_signatures() -> dict[str, str]:
    """
    Inspect the Hindsight client's public API without making any network call.
    Returns a dict of method_name → signature_string.
    """
    if not _have_package:
        logger.warning(
            "Package 'hindsight_client' is not installed.\n"
            "Install it with: pip install hindsight-client"
        )
        return {}

    sigs: dict[str, str] = {}
    logger.info("Package 'hindsight_client' found — module: %s",
                inspect.getfile(Hindsight))

    for mname in ("__init__", "retain", "recall", "reflect",
                  "aretain", "arecall", "areflect"):
        method = getattr(Hindsight, mname, None)
        if method is not None:
            try:
                sig = str(inspect.signature(method))
                sigs[mname] = sig
                logger.info("  Hindsight.%s%s", mname, sig)
            except (ValueError, TypeError) as exc:
                logger.warning("  .%s — could not inspect: %s", mname, exc)

    return sigs


def _live_test() -> bool:
    api_key = os.getenv("HINDSIGHT_API_KEY", "")
    base_url = os.getenv("HINDSIGHT_BASE_URL", "")
    bank_id = os.getenv("HINDSIGHT_BANK_ID", "ustaad-site1")

    if not api_key or not base_url:
        logger.info(
            "\nLive test SKIPPED — HINDSIGHT_API_KEY / HINDSIGHT_BASE_URL not set.\n"
            "To run the live test:\n"
            "  1. Create an account at https://hindsight.vectorize.io/\n"
            "  2. Add HINDSIGHT_API_KEY and HINDSIGHT_BASE_URL to .env\n"
            "  3. Re-run:  python scripts/hindsight_smoke_test.py\n"
            "\nHindsightMemory is marked 'live-untested' in README until then."
        )
        return True  # skip ≠ failure

    if not _have_package:
        logger.error("Cannot run live test: 'hindsight_client' not installed.")
        return False

    logger.info("Keys found — running live round-trip …")
    try:
        client = Hindsight(base_url=base_url, api_key=api_key)

        test_text = (
            "SMOKE TEST | Ustaad | offline-verify\n"
            "Signature: Pump-2: current 1.2x baseline, temperature rising (+1.5 C/min), "
            "gas normal, 3 noise spikes/min, panel closed, 5 min after startup.\n"
            "Action taken by system: smoke test retain."
        )
        logger.info("retain() → %r …", test_text[:60])
        resp = client.retain(
            bank_id=bank_id,
            content=test_text,
            tags=["machine:Pump-2", "worker:smoke_test"],
            metadata={"source": "smoke_test"},
        )
        logger.info("  retain success=%s items=%s", resp.success, resp.items_count)

        logger.info("recall() …")
        recall_resp = client.recall(
            bank_id=bank_id,
            query="Pump-2 current elevated temperature rising",
            max_tokens=1024,
            budget="low",
        )
        logger.info("  recall returned %d result(s)", len(recall_resp.results))
        for r in recall_resp.results[:2]:
            logger.info("    id=%s text=%r…", r.id, (r.text or "")[:80])

        logger.info("reflect() …")
        ref_resp = client.reflect(
            bank_id=bank_id,
            query="What patterns of faults have been seen on Pump-2?",
            budget="low",
        )
        logger.info("  reflect text: %s", ref_resp.text[:200] if ref_resp.text else "(empty)")

        logger.info("✓ Live round-trip PASSED")
        return True

    except Exception as exc:
        logger.error("✗ Live round-trip FAILED: %s", exc, exc_info=True)
        return False


def main() -> None:
    logger.info("=" * 60)
    logger.info("Hindsight client inspection (offline)")
    logger.info("=" * 60)

    sigs = _inspect_signatures()

    if sigs:
        logger.info("\nVerified signatures written to scripts/_hindsight_sigs.json")
        out = Path(__file__).parent / "_hindsight_sigs.json"
        out.write_text(json.dumps(sigs, indent=2))
    else:
        logger.warning("No signatures found.")

    logger.info("\n" + "=" * 60)
    logger.info("Live round-trip test")
    logger.info("=" * 60)

    ok = _live_test()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
