/*
 * test_safety_logic.c — Host-side unit tests for safety_logic.c
 *
 * Compiled and run with: make -C firmware/frdm_safety test
 * Uses stub HAL implementations (no real hardware needed).
 */
#include "safety_logic.h"
#include "hal.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

/* ── Stub HAL ───────────────────────────────────────────────────────────────  */

static int   stub_relay_state = 1;
static char  stub_uart_buf[4096];
static int   stub_uart_pos = 0;
static uint32_t stub_millis_val = 0;

int32_t adc_read_ma(void)          { return 380; }
void    relay_set(int state)       { stub_relay_state = state; }
void    led_set(int state)         { (void)state; }
void    uart_write(const char *l)  {
    int n = (int)strlen(l);
    if (stub_uart_pos + n < (int)sizeof(stub_uart_buf)) {
        memcpy(stub_uart_buf + stub_uart_pos, l, n);
        stub_uart_pos += n;
    }
}
uint32_t millis(void) { return stub_millis_val += 1000; }

static void reset_stubs(void) {
    stub_relay_state = 1;
    stub_uart_pos = 0;
    memset(stub_uart_buf, 0, sizeof(stub_uart_buf));
    stub_millis_val = 0;
}

/* ── Helpers ────────────────────────────────────────────────────────────────  */

static void run_calibration(int32_t current_ma) {
    for (int i = 0; i < BASELINE_WINDOW_S; i++) {
        safety_tick(current_ma);
    }
}

#define ASSERT(cond, msg) \
    do { if (!(cond)) { fprintf(stderr, "FAIL: %s\n", msg); return 0; } } while(0)

/* ── Tests ──────────────────────────────────────────────────────────────────  */

static int test_calibration(void) {
    reset_stubs();
    safety_init();
    run_calibration(380);
    ASSERT(safety_get_state() == SAFETY_NORMAL, "state should be NORMAL after calibration");
    ASSERT(safety_get_baseline_ma() == 380, "baseline should be 380 mA");
    ASSERT(stub_relay_state == 1, "relay should be ON after calibration");
    printf("PASS test_calibration\n");
    return 1;
}

static int test_no_trip_at_safe_ratio(void) {
    reset_stubs();
    safety_init();
    run_calibration(380);
    /* 1.5x — below 1.8x threshold */
    for (int i = 0; i < 10; i++) safety_tick(570);
    ASSERT(safety_get_state() == SAFETY_NORMAL, "should stay NORMAL at 1.5x");
    ASSERT(stub_relay_state == 1, "relay should stay ON");
    printf("PASS test_no_trip_at_safe_ratio\n");
    return 1;
}

static int test_trip_on_consecutive_overcurrent(void) {
    reset_stubs();
    safety_init();
    run_calibration(380);
    /* 1.9x for 3 consecutive ticks — must trip */
    int32_t overcurrent = (int32_t)(380 * 1.9f);  /* ~722 mA */
    for (int i = 0; i < TRIP_CONSECUTIVE_SAMPLES; i++) {
        safety_tick(overcurrent);
    }
    ASSERT(safety_get_state() == SAFETY_TRIPPED, "should be TRIPPED after 3 overcurrent ticks");
    ASSERT(stub_relay_state == 0, "relay should be OFF");
    ASSERT(strstr(stub_uart_buf, "CUTOFF") != NULL, "CUTOFF event should be emitted");
    printf("PASS test_trip_on_consecutive_overcurrent\n");
    return 1;
}

static int test_no_trip_on_two_samples(void) {
    reset_stubs();
    safety_init();
    run_calibration(380);
    int32_t overcurrent = (int32_t)(380 * 1.9f);
    safety_tick(overcurrent);
    safety_tick(overcurrent);
    safety_tick(300); /* drops below threshold */
    ASSERT(safety_get_state() == SAFETY_NORMAL, "should NOT trip on only 2 consecutive samples");
    printf("PASS test_no_trip_on_two_samples\n");
    return 1;
}

static int test_hard_limit_trip(void) {
    reset_stubs();
    safety_init();
    run_calibration(380);
    safety_tick(OVERCURRENT_HARD_LIMIT_MA); /* absolute hard limit */
    ASSERT(safety_get_state() == SAFETY_TRIPPED, "hard limit should trip immediately");
    ASSERT(stub_relay_state == 0, "relay should be OFF");
    printf("PASS test_hard_limit_trip\n");
    return 1;
}

static int test_reset_after_trip(void) {
    reset_stubs();
    safety_init();
    run_calibration(380);
    int32_t overcurrent = (int32_t)(380 * 1.9f);
    for (int i = 0; i < TRIP_CONSECUTIVE_SAMPLES; i++) safety_tick(overcurrent);
    ASSERT(safety_get_state() == SAFETY_TRIPPED, "should be tripped");

    int ok = safety_reset("W-07");
    ASSERT(ok == 1, "reset should succeed with valid token");
    ASSERT(safety_get_state() == SAFETY_NORMAL, "should be NORMAL after reset");
    ASSERT(stub_relay_state == 1, "relay should be ON after reset");
    printf("PASS test_reset_after_trip\n");
    return 1;
}

static int test_empty_token_rejected(void) {
    reset_stubs();
    safety_init();
    run_calibration(380);
    int32_t overcurrent = (int32_t)(380 * 1.9f);
    for (int i = 0; i < TRIP_CONSECUTIVE_SAMPLES; i++) safety_tick(overcurrent);

    int ok = safety_reset("");
    ASSERT(ok == 0, "empty token should be rejected");
    ASSERT(safety_get_state() == SAFETY_TRIPPED, "should remain TRIPPED");
    printf("PASS test_empty_token_rejected\n");
    return 1;
}

/* ── Main ───────────────────────────────────────────────────────────────────  */

int main(void) {
    int passed = 0, total = 0;
    total++; passed += test_calibration();
    total++; passed += test_no_trip_at_safe_ratio();
    total++; passed += test_trip_on_consecutive_overcurrent();
    total++; passed += test_no_trip_on_two_samples();
    total++; passed += test_hard_limit_trip();
    total++; passed += test_reset_after_trip();
    total++; passed += test_empty_token_rejected();

    printf("\n%d / %d tests passed.\n", passed, total);
    return (passed == total) ? 0 : 1;
}

