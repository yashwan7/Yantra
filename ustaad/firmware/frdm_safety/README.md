# FRDM Safety Board — Firmware README

## Purpose

Provides deterministic overcurrent protection for the motor/pump.
**The relay trip decision is made entirely in C firmware — no LLM, no network,
no Python is involved in the safety path.**

## Safety Rules (implemented in `safety_logic.c`)

1. **Baseline calibration**: first 10 seconds of `safety_tick()` calls accumulate
   a baseline current average.
2. **Ratio trip**: current > 1.8× baseline for **3 consecutive 1-second samples**
   → relay OFF, `CUTOFF` JSON line emitted on UART.
3. **Hard limit**: current ≥ 800 mA → immediate trip (single sample).
4. **Latched trip**: relay stays OFF until a valid `RESET` command or physical button.

## UART JSON Protocol

Every tick emits:
```json
{"ts":1730900001,"i_ma":412,"i_base_ma":380,"ratio":1.08,"relay":"ON"}
```

Trip event:
```json
{"ts":1730900120,"event":"CUTOFF","reason":"OVERCURRENT","i_ma":705,"ratio":1.86}
```

## Host Unit Tests

```bash
make -C firmware/frdm_safety test
```

Requires `gcc`. If not available, the C test is skipped (noted in root README).
The safety logic thresholds are covered by the Python anomaly tests, which model
the same trip conditions.

## UNTESTED on hardware

The HAL (`hal.h`) must be implemented against the MCUXpresso SDK for the target
FRDM board. The safety_logic.c / .h files are hardware-agnostic.

