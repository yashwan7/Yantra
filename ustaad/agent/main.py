"""
Ustaad agent entry point.

Usage:
    python -m agent.main
"""
# Phase 0 stub — full implementation added in Phase 1+
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Ustaad agent starting (stub — full impl in Phase 1+)")


if __name__ == "__main__":
    main()
