/*
 * safety_logic.h — Deterministic overcurrent protection for FRDM board
 *
 * The relay trip decision is made entirely in C firmware.
 * No LLM, no network, no Python involved in the safety path.
 *
 * Trip rule:
 *   current > 1.8 × baseline for 3 consecutive 1-second samples,
 *   OR absolute current > OVERCURRENT_HARD_LIMIT_MA.
 * Trip is LATCHED; cleared only by reset_safety() with a valid token.
 *
 * UNTESTED — hardware HAL not implemented here.
 */
#pragma once
#include <stdint.h>

#define BASELINE_WINDOW_S        10    /* seconds to collect baseline */
#define TRIP_RATIO_THRESHOLD     1.8f  /* ratio to trigger soft trip */
#define TRIP_CONSECUTIVE_SAMPLES 3     /* samples above ratio before trip */
#define OVERCURRENT_HARD_LIMIT_MA 800  /* absolute hard limit */

typedef enum {
    SAFETY_IDLE       = 0,
    SAFETY_CALIBRATING = 1,
    SAFETY_NORMAL     = 2,
    SAFETY_TRIPPED    = 3,
} SafetyState;

/* Initialise; call once after boot */
void safety_init(void);

/* Call every 1 second with the latest current reading */
void safety_tick(int32_t current_ma);

/* Attempt a reset.  token must match last RESET command received. */
int safety_reset(const char *token);

/* Physical button reset flag (set by ISR) */
void safety_button_reset(void);

/* Get current state */
SafetyState safety_get_state(void);

/* Get calibrated baseline in mA (valid after CALIBRATING phase) */
int32_t safety_get_baseline_ma(void);
