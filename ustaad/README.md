# Ustaad — Industrial Incident-Response Agent

Ustaad is an intelligent incident-response agent for industrial machinery (pumps, fans, compressors) featuring persistent memory powered by **Hindsight** (Vectorize).

The agent monitors continuous multi-sensor telemetry, deterministically identifies anomalies, recalls matching past incidents from persistent memory, advises technicians on verified resolutions, and **closes the loop** by verifying telemetry post-fix to learn whether the repair worked or failed. Over time, Ustaad recognizes weak precursor patterns and warns operators prior to hard electrical cutoff faults.

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│  HARDWARE SENSING LAYER (Optional — SIMULATOR=1 bypasses hardware)    │
│                                                                        │
│  ESP32 (Temp/Hum/Gas/Noise/Door) ──MQTT──► Ustaad Agent (Python)       │
│  FRDM MCX Board (Current Shunt)  ──UART──►   • Features (60s rolling)  │
│  Uno Q MCU (RFID + TFT Screen)   ──MQTT──►   • Deterministic Anomaly   │
│                                              • Closed-Loop State Mach  │
│                                                   │       ▲            │
│  PERSISTENT MEMORY (Vectorize Hindsight) ◄────────┴───────┘            │
│  • retain(): Incidents, Fixes, Outcomes                                │
│  • recall(): Semantic similarity query                                 │
│  • reflect(): Systemic root cause synthesis                            │
│                                                                        │
│  DETERMINISTIC SAFETY DOMAIN (C Firmware):                             │
│  FRDM Firmware (safety_logic.c) ──► Latched Relay Cutoff               │
│  * The LLM is NEVER in the safety path. Relay cutoff is decided strictly│
│    by deterministic firmware logic. The LLM only advises.              │
└────────────────────────────────────────────────────────────────────────┘
```

The detailed system interaction graph is documented in [architecture.mmd](file:///Users/yashwanth/Documents/microsoft hackathon/ustaad/docs/architecture.mmd).

---

## 3-Command Quick Start (Simulator Mode)

Run the full system in-process with zero hardware and zero API keys required:

```bash
# 1. Enter repository and activate virtual environment
cd ustaad && source .venv/bin/activate

# 2. Run the automated 3-incident demonstration arc
python scripts/run_demo.py --fresh

# 3. Launch the agent and interactive industrial dashboard
python -m agent.main
```

Open your browser to <http://localhost:8000> to interact with live telemetry, trigger industrial anomaly scenarios, scan technician RFID badges, and view the real-time persistent memory timeline.

---

## How Hindsight is Used

Ustaad leverages Hindsight (Vectorize) for persistent vector memory across three primary primitives: `retain`, `recall`, and `reflect`.

### 1. `retain(content, tags, metadata)`
Persists incident observations, corrective actions taken by technicians, and empirical post-repair sensor verifications.

* **Incident Memory:**
  ```text
  INCIDENT | Pump-2 | 2024-11-01 09:14 | severity: high
  Signature: Pump-2: current 1.5x baseline, temperature rising (+1.8 C/min), gas normal, 5 noise spikes/min, panel closed, 140 min after startup.
  Action taken by system: Overcurrent cutoff triggered, power cut.
  Responder: unassigned.
  ```

* **Fix Applied Memory:**
  ```text
  FIX | Pump-2 | 2024-11-01 09:29 | by W-07
  Root cause: Dry motor bearings causing friction drag. Fix applied: Lubricated.
  ```

* **Outcome Verification Memory:**
  ```text
  OUTCOME | Pump-2 | 2024-11-01 10:44
  Fix "Lubricated" WORKED. current back to 1.05x baseline for 10 min.
  ```

### 2. `recall(query, budget="mid", limit=5)`
When an anomaly occurs, Ustaad builds a deterministic signature string and queries Hindsight to retrieve the top historical matches:
```python
results = client.recall(
    bank_id="ustaad-site1",
    query="Pump-2: current 1.5x baseline, temperature rising (+1.8 C/min), 5 noise spikes/min",
    budget="mid"
)
```

### 3. `reflect(query, budget="low")`
Generates high-level systemic insights across the entire bank to identify recurring component failures:
```python
synthesis = client.reflect(
    bank_id="ustaad-site1",
    query="What recurring fault patterns, failure root causes, and successful repairs have occurred on Pump-2?"
)
```

> **Live vs Local Fallback:** When `HINDSIGHT_API_KEY` is present in `.env`, Ustaad connects directly to Hindsight cloud/self-hosted instances. When missing or `SIMULATOR=1`, Ustaad seamlessly falls back to `LocalMemory` (`data/local_memory.jsonl`) using token-overlap similarity scoring.

---

## Safety Design

1. **Hardware Interlock Boundary:** The electrical cutoff decision is implemented entirely in portable C (`firmware/frdm_safety/safety_logic.c`) running on the microcontroller.
2. **Deterministic Trip Rule:** Power is cut if current exceeds 1.8× calibrated baseline for 3 consecutive 1-second samples, or if absolute current exceeds 800 mA.
3. **Latched State:** Once tripped, the relay cannot be re-engaged by software commands alone. It requires an authorized on-site technician to badge in via RFID and submit an authenticated reset request.
4. **Advisory LLM:** The LLM runs out-of-band as an advisor only. If the LLM is slow, hallucinates, or network connectivity drops, the deterministic safety interlock operates without degradation.

---

## Honest Limitations

* **DHT11 Sampling Latency:** DHT11 sensors update at at most 1 Hz with ±2 °C accuracy. A 60-second rolling linear regression window is used to filter out noise, but high-frequency thermal spikes may lag.
* **Microphone DO Module:** The digital sound sensor provides an interrupt-driven spike flag count rather than calibrated decibel audio streaming.
* **Synthetic Seed History:** The baseline historical records in `agent/seed_history.py` (29 entries across Pump-2, Fan-1, Compressor-3) are synthetically generated to model real-world bearing wear, mounting bolt loosening, and precursor acoustic patterns.
* **Firmware Hardware Targets:** Real-world deployment on NXP FRDM MCX and Arduino Uno Q requires board-specific SDK headers (`hal.h` implementation) and official bridge APIs.
