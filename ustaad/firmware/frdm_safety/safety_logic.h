/*
 * safety_logic.h — Deterministic overcurrent protection for FRDM board
 *
 * The relay trip decision is made entirely in C firmware.
 * No LLM, no network, no Python involved in the safety path.
 *
 * Trip rule:
 *   - Tick frequency: 100 ms (10 Hz).
 *   - Inrush blanking window: ratio-based trip is ignored for the first
 *     INRUSH_BLANKING_TICKS (~1.5s) after relay engagement.
 *   - Trip threshold: current > 1.8 × baseline for 3 consecutive 100ms samples (300 ms).
 *   - Hard limit: current >= OVERCURRENT_HARD_LIMIT_MA (configurable hardware ceiling).
 *   - Baseline calibration: collected after inrush spin-up using median filtering.
 *
 * UNTESTED on real hardware — HAL implemented separately against MCUXpresso SDK.
 */
#pragma once
#include <stdint.h>

#define TICK_PERIOD_MS           100   /* 10 Hz sampling rate */
#define INRUSH_BLANKING_TICKS    15    /* 15 * 100ms = 1.5 s startup inrush blanking */
#define BASELINE_SAMPLE_COUNT    20    /* 20 samples = 2.0 s collected after blanking */
#define TRIP_RATIO_THRESHOLD     1.8f  /* ratio to trigger trip */
#define TRIP_CONSECUTIVE_SAMPLES 3     /* 3 consecutive samples @ 100ms = 300 ms trip */

#ifndef OVERCURRENT_HARD_LIMIT_MA
#define OVERCURRENT_HARD_LIMIT_MA 800  /* absolute max current ceiling in mA */
#endif

typedef enum {
    SAFETY_IDLE       = 0,
    SAFETY_CALIBRATING = 1,
    SAFETY_NORMAL     = 2,
    SAFETY_TRIPPED    = 3,
} SafetyState;

/* Initialise; call once after boot */
void safety_init(void);

/* Call every TICK_PERIOD_MS (100 ms) with the latest current reading */
void safety_tick(int32_t current_ma);

/* Attempt a reset. token must match last RESET command received. */
int safety_reset(const char *token);

/* Physical button reset flag (set by ISR) */
void safety_button_reset(void);

/* Get current state */
SafetyState safety_get_state(void);

/* Get calibrated baseline in mA (valid after CALIBRATING phase) */
int32_t safety_get_baseline_ma(void);

/* Check if currently in inrush blanking window */
int safety_in_inrush_blanking(void);
