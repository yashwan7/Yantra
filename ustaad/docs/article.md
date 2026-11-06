# Turning Sensor Readings Into Sentences for Hindsight Recall

In industrial manufacturing, every plant has that one veteran technician who can listen to a pump for five seconds and tell you: *"That rattle is the drive-end bearing running dry. Grease it, but if it comes back next week, tighten the mounting bolts."*

When that technician retires or changes shifts, that hard-won empirical intuition leaves with them. Traditional SCADA and predictive maintenance dashboards display time-series charts, FFT spectra, and threshold alerts, but they lack episodic memory. They do not remember what a technician did the last time an anomaly occurred, and more critically, they have no idea whether that intervention actually resolved the problem.

To solve this, we engineered **Yantra**: an autonomous incident-response agent for industrial machinery (pumps, fans, compressors) built on long-term agent memory powered by [Vectorize Hindsight](https://hindsight.vectorize.io/).

---

## The Core Technical Challenge: Vectors vs. Sentences

Traditional vector databases index high-dimensional embeddings. But raw time-series data from microcontrollers—such as 100 Hz current samples, thermocouple voltages, and acoustic spike flags—cannot simply be shoved into a semantic vector database. A raw tuple like `{"i_ma": 720.0, "ratio": 1.9, "temp_c": 35.2, "noise": 5}` means nothing to a semantic retrieval system.

Vectorize Hindsight operates on a higher abstraction layer than raw vector stores: when you retain text into Hindsight, an internal language model extracts core facts, causal relationships, entities, and temporal bounds.

To bridge the gap between high-frequency embedded telemetry and episodic memory, we designed a deterministic **signature-to-text transformation layer** (`agent/signature.py`).

### The Signature Engine

Instead of feeding raw floating-point numbers directly, telemetry is processed through a 60-second rolling window that extracts physical dynamics:
- Ratio of current relative to a calibrated baseline (`current_ratio`)
- Temperature rate of change (`temp_slope_c_per_min`) computed via normalized linear regression
- Gas/volatile organic compound deviation from baseline (`gas_delta`)
- Acoustic/vibration spikes per minute (`noise_per_min`)
- Physical enclosure status (`door_open`) via optical LDR
- Equipment uptime since last startup (`uptime_min`)

These features are then discretized into semantic qualitative buckets so that minor analog noise does not alter the sentence structure:

```python
# agent/signature.py
from __future__ import annotations
from typing import Any

def signature_text(machine_id: str, f: dict[str, Any]) -> str:
    """
    Convert numerical telemetry features into a deterministic natural language sentence.
    
    Hindsight recall processes natural language queries rather than raw numeric vectors.
    Transforming features into structured sentences ensures consistent indexing, fact
    extraction, and high-fidelity semantic recall.
    """
    ratio = float(f.get("current_ratio", 1.0))
    temp_slope = float(f.get("temp_slope_c_per_min", 0.0))
    gas_delta = float(f.get("gas_delta", 0.0))
    noise = float(f.get("noise_per_min", 0.0))
    door = bool(f.get("door_open", False))
    uptime = float(f.get("uptime_min", 0.0))

    if temp_slope > 1.0:
        temp_str = f"temperature rising ({temp_slope:+.1f} C/min)"
    elif temp_slope < -1.0:
        temp_str = f"temperature falling ({temp_slope:+.1f} C/min)"
    else:
        temp_str = f"temperature stable ({temp_slope:+.1f} C/min)"

    gas_str = "gas elevated" if gas_delta > 150.0 else "gas normal"
    door_str = "panel door open" if door else "panel closed"

    parts = [
        f"{machine_id}: current {ratio:.1f}x baseline",
        temp_str,
        gas_str,
        f"{noise:.0f} noise spikes/min",
        door_str,
        f"{uptime:.0f} min after startup",
    ]
    return ", ".join(parts)
```

For example, when a pump begins to seize, the raw sensor readings become:
```text
Pump-2: current 1.9x baseline, temperature rising (+2.0 C/min), gas normal, 5 noise spikes/min, panel closed, 12 min after startup.
```

This sentence serves both as the **retained memory text** and as the **recall query**. Because the format is consistent, Hindsight's semantic search accurately retrieves related historical incidents across disparate dates and operational shifts.

---

## Architectural Hard Rule: LLM Never Controls Safety

A fundamental principle of industrial automation is that probabilistic models must never sit in the safety critical path. If a motor stalls, overcurrent can burn out windings or ignite insulation within seconds. Waiting for an LLM API round-trip to decide whether to trip a contactor is unacceptable.

In Yantra, safety is decoupled from intelligence:
1. **Safety Path (Firmware):** Deterministic C firmware running on an NXP FRDM MCXN236 microcontroller samples current at 100 Hz. If current exceeds 1.8x baseline for 3 consecutive 100 ms samples (with a 1.5-second startup inrush blanking window), the microcontroller instantly de-energizes the safety relay via hardware GPIO and latches the state. It operates with zero cloud or network connectivity.
2. **Intelligence Path (Python Agent):** The agent receives the `CUTOFF` event over UART/MQTT, transforms the telemetry into a symptom signature, queries Hindsight for past incidents, and prompts an LLM (Groq) to advise the on-site technician.
3. **Accountability Path (Physical Badging):** Relay reset cannot be executed remotely or automatically by the LLM. An on-site technician must physically badge in via an RFID reader and select their chosen fix on a local display.

---

## The Closed Loop: Why Retaining "Fix Outcomes" is the Game Changer

Most diagnostic systems stop after giving advice. Yantra closes the feedback loop.

When a technician applies a fix (e.g., *"Lubricated bearings"*), the agent does not immediately assume the problem is solved. Instead, it enters a `VERIFYING` state:
- It tracks sensor telemetry over a verification window (configurable from 90 seconds in demo mode to 10 minutes in production).
- If the current ratio returns to `< 1.15x` baseline and temperature stabilizes, the verification succeeds.
- The agent retains an `OUTCOME` record to Hindsight:
  ```text
  OUTCOME | Pump-2 | 2026-11-06 14:52
  Fix "Lubricated" WORKED. Current ratio returned to 1.02x baseline and remained stable.
  ```
- If the current surges or trips again during verification, the fix is marked `FAILED`, the incident escalates, and the failure is permanently recorded in memory.

### Real Demonstration: Incident 1 vs. Incident 2

Here is how the learning curve unfolds in practice:

#### Incident 1: Cold Start
On a fresh deployment with no history for `Pump-2`, an overcurrent cutoff occurs.
- **Hindsight Recall:** Returns 0 matching records.
- **Agent Advisory:** Pure generic advice:
  ```text
  ADVISORY: Anomaly detected on Pump-2. No prior matching incidents in memory. 
  Recommend immediate visual inspection of motor mounts, belt tension, and bearings.
  ```
- **Action & Verification:** Technician W-07 badges in, applies *"Lubricated"*, and resets the relay. Sensors confirm current returns to 1.02x. Hindsight retains the `WORKED` outcome.

#### Incident 2: Recurrent Pattern
When the same mechanical drag recurs days later:
- **Hindsight Recall:** Recalls the previous incident and its verified outcome.
- **Agent Advisory (via Groq + Hindsight):**
  ```text
  Diagnostic Summary:
  - Symptom: Current at 1.9x baseline, temperature rising (+2.0 C/min), 5 noise spikes/min.
  - Historical Resolution: Bearing lubrication resolved this exact signature in 100% of recorded cases (1/1 success).
  
  Recommended Action:
  1. Verify machine is de-energized.
  2. Inspect drive-end bearing races for lubricant starvation.
  3. Apply OEM high-temperature synthetic grease.
  4. Badge in on-site to request safety relay re-engagement.
  ```

#### Incident 3: Proactive Precursor Warning
Because Hindsight retains temporal context, the agent notes that prior hard cutoffs were preceded by subtle precursor signatures (current at 1.25x baseline and elevated acoustic noise). When these weak signals appear simultaneously, Yantra issues an **EARLY WARNING** alert on the technician's screen *before* the hardware overcurrent relay ever trips, preventing unplanned factory downtime.

---

## Honest Limitations and Production Engineering

Deploying edge AI with persistent memory revealed several real-world engineering constraints:
1. **Sensor Bandwidth:** Low-cost DHT11 sensors take 1 to 2 seconds to stabilize. Temperature slope calculations require regression over at least 30–60 seconds to avoid false noise spikes.
2. **Acoustic Discrimination:** Basic LM2903 microphone modules provide digital threshold comparator flags rather than raw audio streams. We treated them strictly as pulse counters (`noise_per_min`) rather than attempting onboard acoustic FFT.
3. **Motor Inrush Current:** Industrial DC motors draw 3x to 6x rated current during spin-up. Without an initial 1.5-second blanking window in firmware, the safety relay trips immediately upon reset.

---

## Conclusion

Industrial AI agents must do more than just process prompt templates; they must build persistent, verifiable operational experience. By translating analog telemetry into natural language symptom signatures and coupling semantic memory with deterministic safety firmware, Yantra provides a blueprint for resilient, self-learning industrial systems.

To explore the architecture, client SDK, and persistent memory concepts:
- [Vectorize Hindsight GitHub Repository](https://github.com/vectorize-io/hindsight)
- [Vectorize Hindsight Documentation & Cloud Console](https://hindsight.vectorize.io/)
- [Understanding Agent Memory Architecture](https://vectorize.io/what-is-agent-memory)

