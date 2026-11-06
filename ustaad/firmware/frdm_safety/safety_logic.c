/*
 * safety_logic.c — Deterministic overcurrent protection with inrush blanking
 *
 * All hardware access goes through hal.h so this file can be unit-tested
 * on a host with stub HAL implementations.
 *
 * UNTESTED on real hardware — HAL not implemented here.
 */
#include "safety_logic.h"
#include "hal.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ── internal state ────────────────────────────────────────────────────────── */

static SafetyState   s_state             = SAFETY_IDLE;
static int32_t       s_baseline_ma       = 0;
static int32_t       s_cal_samples[BASELINE_SAMPLE_COUNT];
static int           s_cal_count         = 0;
static int           s_consec_over       = 0;
static int           s_inrush_countdown  = 0;
static int           s_tick_count        = 0;
static char          s_reset_token[64]   = {0};

/* ── helpers ────────────────────────────────────────────────────────────────  */

static void emit_json_line(const char *event, int32_t current_ma, float ratio) {
    char buf[256];
    uint32_t ts = millis() / 1000u;
    snprintf(buf, sizeof(buf),
             "{\"ts\":%lu,\"event\":\"%s\",\"i_ma\":%ld,\"ratio\":%.2f}\r\n",
             (unsigned long)ts, event, (long)current_ma, (double)ratio);
    uart_write(buf);
}

static void emit_status(int32_t current_ma) {
    char buf[256];
    uint32_t ts = millis() / 1000u;
    float ratio = (s_baseline_ma > 0)
                  ? (float)current_ma / (float)s_baseline_ma
                  : 0.0f;
    const char *relay_str = (s_state == SAFETY_TRIPPED) ? "OFF" : "ON";
    snprintf(buf, sizeof(buf),
             "{\"ts\":%lu,\"i_ma\":%ld,\"i_base_ma\":%ld,\"ratio\":%.2f,"
             "\"relay\":\"%s\"}\r\n",
             (unsigned long)ts, (long)current_ma, (long)s_baseline_ma,
             (double)ratio, relay_str);
    uart_write(buf);
}

static int compare_int32(const void *a, const void *b) {
    int32_t diff = (*(const int32_t *)a - *(const int32_t *)b);
    return (diff > 0) - (diff < 0);
}

static int32_t compute_median(int32_t *arr, int n) {
    qsort(arr, n, sizeof(int32_t), compare_int32);
    return arr[n / 2];
}

/* ── public API ─────────────────────────────────────────────────────────────  */

void safety_init(void) {
    s_state            = SAFETY_CALIBRATING;
    s_baseline_ma      = 0;
    s_cal_count        = 0;
    s_consec_over      = 0;
    s_tick_count       = 0;
    s_inrush_countdown = INRUSH_BLANKING_TICKS;  /* 1.5 s blanking */
    memset(s_reset_token, 0, sizeof(s_reset_token));
    relay_set(1);  /* relay ON at startup */
    led_set(1);
}

void safety_tick(int32_t current_ma) {
    s_tick_count++;

    if (s_inrush_countdown > 0) {
        s_inrush_countdown--;
    }

    /* ── calibration phase ───────────────────────────────────────────── */
    if (s_state == SAFETY_CALIBRATING) {
        /* Wait until spin-up inrush has settled before capturing baseline */
        if (s_inrush_countdown == 0) {
            s_cal_samples[s_cal_count++] = current_ma;
            if (s_cal_count >= BASELINE_SAMPLE_COUNT) {
                s_baseline_ma = compute_median(s_cal_samples, s_cal_count);
                s_state = SAFETY_NORMAL;
                char buf[128];
                snprintf(buf, sizeof(buf),
                         "{\"event\":\"CALIBRATED\",\"baseline_ma\":%ld}\r\n",
                         (long)s_baseline_ma);
                uart_write(buf);
            }
        }
        return;
    }

    /* ── tripped: relay is OFF, emit status ─────────────────────────── */
    if (s_state == SAFETY_TRIPPED) {
        emit_status(current_ma);
        return;
    }

    /* ── normal operation ───────────────────────────────────────────── */
    emit_status(current_ma);

    /* Absolute hard limit applies always (e.g. dead short circuit) */
    if (current_ma >= OVERCURRENT_HARD_LIMIT_MA) {
        relay_set(0);
        led_set(0);
        s_state = SAFETY_TRIPPED;
        float ratio = (s_baseline_ma > 0)
                      ? (float)current_ma / (float)s_baseline_ma : 999.0f;
        emit_json_line("CUTOFF", current_ma, ratio);
        return;
    }

    /* Ratio-based trip: IGNORED during inrush blanking window (~1.5s) */
    if (s_inrush_countdown > 0) {
        s_consec_over = 0;
        return;
    }

    if (s_baseline_ma > 0) {
        float ratio = (float)current_ma / (float)s_baseline_ma;
        if (ratio >= TRIP_RATIO_THRESHOLD) {
            s_consec_over++;
            if (s_consec_over >= TRIP_CONSECUTIVE_SAMPLES) {
                relay_set(0);
                led_set(0);
                s_state = SAFETY_TRIPPED;
                emit_json_line("CUTOFF", current_ma, ratio);
            }
        } else {
            s_consec_over = 0;
        }
    }
}

int safety_reset(const char *token) {
    if (token == NULL || token[0] == '\0') {
        return 0;
    }
    s_state = SAFETY_NORMAL;
    s_consec_over = 0;
    s_inrush_countdown = INRUSH_BLANKING_TICKS;  /* blanking window after reset */
    relay_set(1);
    led_set(1);
    char buf[128];
    snprintf(buf, sizeof(buf),
             "{\"event\":\"RESET\",\"worker\":\"%s\"}\r\n", token);
    uart_write(buf);
    return 1;
}

void safety_button_reset(void) {
    safety_reset("BUTTON");
}

SafetyState safety_get_state(void) {
    return s_state;
}

int32_t safety_get_baseline_ma(void) {
    return s_baseline_ma;
}

int safety_in_inrush_blanking(void) {
    return (s_inrush_countdown > 0);
}
