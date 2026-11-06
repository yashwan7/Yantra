"""
agent/ingest.py — sensor ingestion sources.

Three sources share the same interface: they call a callback with a Reading.

  SimSource   — in-process simulator (SIMULATOR=1)
  MqttSource  — PubSubClient subscribing to ESP32 env topic
  SerialSource— reads FRDM JSON lines from /dev/ttyACMx

Sources are composable: in SIMULATOR mode only SimSource runs.
In hardware mode, MqttSource and SerialSource run in parallel threads.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Callable

from agent.config import get_settings
from agent.models import Reading
from agent import simulator as sim_mod

logger = logging.getLogger(__name__)

ReadingCallback = Callable[[Reading], None]


class BaseSource(ABC):
    """Abstract base class for all ingest sources."""

    @abstractmethod
    def start(self, callback: ReadingCallback) -> None:
        """Start producing readings; must not block the caller's thread."""

    @abstractmethod
    def stop(self) -> None:
        """Signal the source to stop."""


# ── SimSource ─────────────────────────────────────────────────────────────────

class SimSource(BaseSource):
    """
    In-process simulator source.  Generates a Reading every 2 seconds.
    Uses agent.simulator to produce realistic baseline + triggered scenarios.
    """

    def __init__(self, interval_s: float = 2.0) -> None:
        self._interval = interval_s
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, callback: ReadingCallback) -> None:
        cfg = get_settings()
        logger.info("SimSource starting (machine=%s)", cfg.machine_id)

        def _run() -> None:
            while not self._stop_event.is_set():
                reading = sim_mod.next_reading(cfg.machine_id)
                try:
                    callback(reading)
                except Exception:
                    logger.exception("SimSource callback error")
                self._stop_event.wait(self._interval)

        self._thread = threading.Thread(target=_run, name="SimSource", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("SimSource stopped")


# ── MqttSource ───────────────────────────────────────────────────────────────

class MqttSource(BaseSource):
    """
    MQTT source — subscribes to ustaad/<site>/<machine>/env.
    Requires paho-mqtt and a running broker (SIMULATOR=0).
    """

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._client = None

    def start(self, callback: ReadingCallback) -> None:
        cfg = get_settings()
        try:
            import paho.mqtt.client as mqtt  # type: ignore[import]
        except ImportError:
            logger.error("paho-mqtt not installed; cannot start MqttSource")
            return

        topic_env = f"{cfg.mqtt_topic_prefix}/env"
        topic_ui = f"{cfg.mqtt_topic_prefix}/ui_event"

        def _on_connect(client, userdata, flags, rc):
            logger.info("MqttSource connected rc=%d, subscribing to %s", rc, topic_env)
            client.subscribe(topic_env)

        def _on_message(client, userdata, msg):
            try:
                data = json.loads(msg.payload)
                r = Reading(
                    ts=data.get("ts", time.time()),
                    temp_c=float(data.get("temp_c", 30.0)),
                    hum=float(data.get("hum", 50.0)),
                    gas_raw=int(data.get("gas_raw", 410)),
                    noise=int(data.get("noise", 0)),
                    ldr_raw=int(data.get("ldr_raw", 2300)),
                    door_open=bool(data.get("door_open", False)),
                    source="mqtt",
                )
                callback(r)
            except Exception:
                logger.exception("MqttSource parse error: %r", msg.payload[:200])

        client = mqtt.Client()
        client.on_connect = _on_connect
        client.on_message = _on_message
        self._client = client

        logger.info("MqttSource connecting to %s:%d", cfg.mqtt_host, cfg.mqtt_port)
        client.connect(cfg.mqtt_host, cfg.mqtt_port, keepalive=60)
        client.loop_start()

    def stop(self) -> None:
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
        logger.info("MqttSource stopped")


# ── SerialSource ──────────────────────────────────────────────────────────────

class SerialSource(BaseSource):
    """
    Serial source — reads FRDM JSON lines from UART.
    Each line is either a status line or a CUTOFF event line.
    Requires pyserial (SIMULATOR=0).
    """

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._port = None

    def start(self, callback: ReadingCallback) -> None:
        cfg = get_settings()
        try:
            import serial  # type: ignore[import]
        except ImportError:
            logger.error("pyserial not installed; cannot start SerialSource")
            return

        def _run() -> None:
            try:
                port = serial.Serial(cfg.serial_port, baudrate=115200, timeout=1)
                self._port = port
                logger.info("SerialSource opened %s", cfg.serial_port)
                while not self._stop_event.is_set():
                    raw = port.readline()
                    if not raw:
                        continue
                    try:
                        data = json.loads(raw.decode("ascii", errors="ignore").strip())
                        cutoff = data.get("event") == "CUTOFF"
                        r = Reading(
                            ts=float(data.get("ts", time.time())),
                            temp_c=0.0,   # FRDM does not send temp
                            hum=0.0,
                            gas_raw=0,
                            noise=0,
                            ldr_raw=0,
                            door_open=False,
                            i_ma=float(data.get("i_ma", 0)),
                            i_base_ma=float(data.get("i_base_ma", 0)),
                            ratio=float(data.get("ratio", 1.0)),
                            relay=data.get("relay", "ON"),
                            cutoff_event=cutoff,
                            cutoff_reason=data.get("reason"),
                            source="serial",
                        )
                        callback(r)
                    except (json.JSONDecodeError, ValueError):
                        logger.debug("SerialSource: non-JSON line: %r", raw[:60])
            except Exception:
                logger.exception("SerialSource error on %s", cfg.serial_port)

        self._thread = threading.Thread(target=_run, name="SerialSource", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._port:
            try:
                self._port.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("SerialSource stopped")


# ── Factory ───────────────────────────────────────────────────────────────────

def build_sources() -> list[BaseSource]:
    """Return the appropriate source(s) based on config."""
    cfg = get_settings()
    if cfg.simulator:
        return [SimSource()]
    return [MqttSource(), SerialSource()]

