/*
 * hal.h — Hardware Abstraction Layer for FRDM safety board
 *
 * UNTESTED — HAL implementations require MCUXpresso SDK.
 * The safety logic (safety_logic.c) calls only these functions;
 * unit tests (test_safety_logic.c) supply stub implementations.
 */
#pragma once
#include <stdint.h>

/* Read current in milliamps from ADC */
int32_t adc_read_ma(void);

/* Control the relay: 1 = ON (powered), 0 = OFF (tripped) */
void relay_set(int state);

/* Control a status LED */
void led_set(int state);

/* Write a null-terminated string to UART */
void uart_write(const char *line);

/* Milliseconds since boot */
uint32_t millis(void);
