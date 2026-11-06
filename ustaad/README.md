# Ustaad — Industrial Incident-Response Agent

Ustaad monitors fans and pumps via sensors, detects anomalies, recalls similar
past incidents from a persistent vector memory (Hindsight by Vectorize), advises
the on-site technician, and verifies whether the applied fix worked. The outcome
is retained so the agent learns over time.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  HARDWARE (optional — SIMULATOR=1 bypasses all of it)                   │
│                                                                         │
│  ESP32 ──MQTT──► Agent (Python)                                         │
│  FRDM  ──Serial─►   ingest → features → anomaly → signature            │
│  Uno Q ──MQTT──►       └─► memory.recall ──► LLM advice                │
│                              └─► closed_loop state machine             │
│                                   └─► memory.retain (outcome)          │
│                                                                         │
│  FRDM ◄──────── relay control is PURELY DETERMINISTIC FIRMWARE (C)     │
│                 The LLM and agent NEVER control the relay.              │
└─────────────────────────────────────────────────────────────────────────┘
```

See `docs/architecture.mmd` for the full Mermaid diagram.

---

## Quick Start (simulator mode — no hardware required)

```bash
cd ustaad
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # SIMULATOR=1 is already set
python -m agent.main          # agent loop + dashboard on http://localhost:8000
```

Then open <http://localhost:8000> and click **Stall** to trigger a scenario.

For the 3-incident demo arc:

```bash
python scripts/run_demo.py
```

---

## How Hindsight is Used

| Action | When | Example text retained |
|--------|------|-----------------------|
| `retain` | Anomaly detected | `INCIDENT \| Pump-2 \| 2024-11-01 09:14 \| severity: high` |
| `retain` | Technician picks fix | `FIX \| Pump-2 \| … \| by W-07 — Fix applied: Lubricated` |
| `retain` | Verify window ends | `OUTCOME \| Pump-2 \| … — Fix "Lubricated" WORKED.` |
| `recall` | Anomaly detected (query = signature sentence) | Returns top-5 similar past incidents |
| `reflect` | Dashboard "Patterns" panel refresh | Returns a natural-language synthesis |

> **Live-untested**: `HindsightMemory` was written against signatures verified by
> `inspect.signature` on the installed package (see Phase 0 report in the README).
> Run `python scripts/hindsight_smoke_test.py` after adding real keys to `.env`
> to confirm end-to-end connectivity.

---

## Safety Design

The relay trip decision lives **entirely** in `firmware/frdm_safety/safety_logic.c`
(portable C, no OS). The rule is: cut power when current > 1.8× baseline for 3
consecutive 1-second samples, or when absolute current exceeds a hard limit.
The relay is latched; only a valid RESET command or physical button clears it.

Python and the LLM observe relay state; they never command it. This ensures the
safety interlock cannot be degraded by a software bug, model hallucination, or
network failure.

---

## Firmware Status

| Firmware | Status |
|----------|--------|
| `esp32_sensor_node` | UNTESTED — requires ESP32 hardware |
| `frdm_safety` | C logic unit-tested on host via gcc (see below); HAL untested |
| `unoq_mcu` | SKELETON — UNTESTED; requires Uno Q MCU bridge API docs |

Host C test (requires gcc):

```bash
make -C firmware/frdm_safety test
```

If `gcc` is not available on the host (e.g. CI without build-essentials), this
target is skipped. The logic is correct by inspection and the Python-side tests
cover the same trip thresholds.

---

## Limitations

- **DHT11 is slow** (1 sample/s, ±2 °C accuracy). Temperature slope is noisy
  at short intervals; the 60-second rolling window mitigates this.
- **Mic module gives only a digital spike flag**, not audio. `noise_per_min` counts
  interrupt-driven spikes, not dB levels.
- **Seeded history is synthetic** and clearly labeled as such in `seed_history.py`.
  It demonstrates the recall/reflect loop but does not represent real plant data.
- **Hindsight vector recall** depends on embedding similarity; edge cases with very
  short or identical memory texts may return unexpected results.
- **LLM advice is not safety-critical**. The agent can fail silently (timeout,
  no key) and the safety interlock continues to operate independently.
