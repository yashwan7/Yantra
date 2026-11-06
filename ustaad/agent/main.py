"""
agent/main.py — Ustaad entrypoint.

Starts:
  1. Sensor ingestion & feature computation pipeline
  2. Closed-loop incident response state machine
  3. FastAPI industrial dashboard on http://0.0.0.0:8000
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import uvicorn

from agent.anomaly import classify
from agent.closed_loop import ClosedLoopController
from agent.config import get_settings
from agent.features import compute_features
from agent.ingest import build_sources
from agent.memory import get_memory_store
from agent.models import Reading
from agent.seed_history import seed_memory
from agent.state import SharedState
from dashboard.app import app, set_shared_state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ustaad")


def _agent_loop(state: SharedState, stop_event: threading.Event) -> None:
    """Core background loop: feature extraction and closed-loop stepping."""
    cfg = get_settings()
    controller = ClosedLoopController(state)
    logger.info("Agent controller loop started for machine '%s'", cfg.machine_id)

    last_feature_calc = 0.0

    while not stop_event.is_set():
        now = time.time()

        # Compute features every 2 seconds
        if now - last_feature_calc >= 2.0:
            readings = state.get_readings()
            if readings and len(readings) >= 3:
                feat = compute_features(readings, cfg.machine_id)
                if feat:
                    latest_r = state.latest_reading()
                    classified_feat = classify(feat, latest_reading=latest_r)
                    state.set_features(classified_feat)
            last_feature_calc = now

        # Step closed-loop state machine
        try:
            controller.step()
        except Exception:
            logger.exception("Error in closed-loop controller step")

        time.sleep(0.5)

    logger.info("Agent controller loop stopped")


def main() -> None:
    cfg = get_settings()
    logger.info("Starting Ustaad (machine=%s, site=%s, sim=%s)", cfg.machine_id, cfg.site, cfg.simulator)

    # Initialize shared state
    state = SharedState()
    set_shared_state(state)

    # Initialize memory store and outcome ledger, seed if empty
    store = get_memory_store()
    local_mem_file = Path("data/local_memory.jsonl")
    ledger_file = Path("data/outcome_ledger.json")
    if not local_mem_file.exists() or local_mem_file.stat().st_size == 0 or not ledger_file.exists():
        logger.info("Local memory or outcome ledger empty, seeding initial 60-day history...")
        seed_memory(store)

    # Start Ingest sources
    sources = build_sources()
    for s in sources:
        s.start(callback=state.push_reading)

    # Start Agent controller thread
    stop_event = threading.Event()
    agent_thread = threading.Thread(target=_agent_loop, args=(state, stop_event), name="AgentLoop", daemon=True)
    agent_thread.start()

    logger.info("Ustaad dashboard accessible at http://0.0.0.0:8000")
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
    finally:
        stop_event.set()
        for s in sources:
            s.stop()
        agent_thread.join(timeout=2.0)
        logger.info("Ustaad shutdown complete.")


if __name__ == "__main__":
    main()
