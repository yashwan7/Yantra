"""
agent/config.py — configuration loaded from .env with pydantic-settings.

All env vars match the keys in .env.example exactly.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # LLM
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    # Hindsight
    hindsight_base_url: str = ""
    hindsight_api_key: str = ""
    hindsight_bank_id: str = "ustaad-site1"

    # MQTT
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883

    # Serial
    serial_port: str = "/dev/ttyACM0"

    # Runtime flags
    simulator: bool = True  # SIMULATOR=1 or SIMULATOR=true

    # Site / machine
    machine_id: str = "Pump-2"
    site: str = "site1"

    # Closed-loop timing
    verify_seconds: int = 90
    soft_recall_interval_s: int = 30

    @field_validator("simulator", mode="before")
    @classmethod
    def _parse_bool(cls, v: object) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)

    # ── derived helpers ───────────────────────────────────────────────────────
    @property
    def machine_slug(self) -> str:
        """URL-safe machine id, e.g. 'pump-2' from 'Pump-2'."""
        return self.machine_id.lower().replace(" ", "-")

    @property
    def use_hindsight(self) -> bool:
        return bool(self.hindsight_api_key and self.hindsight_base_url)

    @property
    def use_groq(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def mqtt_topic_prefix(self) -> str:
        return f"ustaad/{self.site}/{self.machine_slug}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    cfg = Settings()
    logger.info(
        "Config loaded: machine=%s site=%s simulator=%s "
        "hindsight=%s groq=%s",
        cfg.machine_id,
        cfg.site,
        cfg.simulator,
        "yes" if cfg.use_hindsight else "no",
        "yes" if cfg.use_groq else "no",
    )
    return cfg

