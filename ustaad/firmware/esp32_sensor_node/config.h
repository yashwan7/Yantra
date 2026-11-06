/*
 * config.h — ESP32 Sensor Node Configuration
 * UNTESTED — requires ESP32 hardware.
 */
#pragma once

// Pin assignments
#define DHT_PIN        4   // DHT11 data pin (3.3 V logic)
#define GAS_ADC_PIN    34  // MQ gas sensor — ADC1_CH6 (safe with WiFi)
#define MIC_DO_PIN     35  // Mic digital output — ADC1_CH7 (interrupt)
#define LDR_PIN        32  // LDR — ADC1_CH4

// Thresholds
#define DOOR_OPEN_LDR_THRESHOLD  2000  // LDR raw counts; tune for enclosure
#define GAS_PUBLISH_INTERVAL_MS  2000

// MQTT topics (site and machine filled from secrets.h at runtime)
#define TOPIC_ENV   "ustaad/%s/%s/env"
#define TOPIC_STATUS "ustaad/%s/%s/status"

