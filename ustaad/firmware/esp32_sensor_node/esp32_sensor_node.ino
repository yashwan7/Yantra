/*
 * esp32_sensor_node.ino — Ustaad ESP32 Telemetry Sensor Node
 *
 * UNTESTED on physical hardware — requires ESP32 dev board and sensors.
 *
 * Hardware connections & design notes:
 *  - DHT11 data pin -> GPIO 4 (3.3V logic)
 *  - MQ-series Gas Sensor Analog Out -> GPIO 34 (ADC1_CH6).
 *    WARNING: ESP32 ADC inputs are max 3.3V. If your MQ sensor board operates
 *    at 5V, use a resistive voltage divider (e.g. 10k/20k) to scale 0-5V to 0-3.3V.
 *    WARNING: Do NOT use ADC2 pins (GPIOs 0, 2, 4, 12, 13, 14, 15, 25, 26, 27)
 *    because ADC2 is disabled when ESP32 Wi-Fi is active!
 *  - Microphone DO (Digital Output spike detector) -> GPIO 35 (ADC1_CH7).
 *    Configured as an interrupt-driven falling-edge counter.
 *    "noise" is a digital spike count in the 2s interval, not raw audio stream.
 *  - LDR Photocell Analog Out -> GPIO 32 (ADC1_CH4).
 *    Used to detect if machine enclosure door is open (ambient light ingress).
 *
 * Telemetry Contract:
 *  Publishes JSON payload to ustaad/<SITE>/<MACHINE>/env every 2000 ms:
 *  {"ts":1730900000,"temp_c":31.0,"hum":52,"gas_raw":410,"noise":0,"ldr_raw":2300,"door_open":false}
 *
 * MQTT Last-Will and Testament (LWT):
 *  Topic: ustaad/<SITE>/<MACHINE>/status
 *  LWT payload: "offline" (retained)
 *  Online payload: "online" (retained)
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include "config.h"

// Credentials from secrets.h (copy secrets.h.example -> secrets.h)
#if __has_include("secrets.h")
#include "secrets.h"
#else
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* MQTT_HOST     = "192.168.1.100";
const int   MQTT_PORT     = 1883;
const char* SITE          = "site1";
const char* MACHINE_ID    = "pump-2";
#endif

// Sensor instances
DHT dht(DHT_PIN, DHT11);
WiFiClient espClient;
PubSubClient mqttClient(espClient);

// Interrupt-safe noise spike counter
volatile uint32_t isr_noise_spikes = 0;
void IRAM_ATTR on_mic_spike_isr() {
    isr_noise_spikes++;
}

// Timing
unsigned long last_publish_ms = 0;
char topic_env[128];
char topic_status[128];

void setup_wifi() {
    delay(10);
    Serial.print("Connecting to WiFi: ");
    Serial.println(WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 20) {
        delay(500);
        Serial.print(".");
        attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.println("\nWiFi connected. IP: ");
        Serial.println(WiFi.localIP());
    } else {
        Serial.println("\nWiFi connection failed! Telemetry will queue or retry.");
    }
}

void reconnect_mqtt() {
    while (!mqttClient.connected()) {
        Serial.print("Connecting to MQTT broker...");
        String clientId = "ESP32_Ustaad_" + String(MACHINE_ID);

        // Last will and testament: topic_status, QoS 1, retain true, payload "offline"
        if (mqttClient.connect(clientId.c_str(), topic_status, 1, true, "offline")) {
            Serial.println("connected.");
            mqttClient.publish(topic_status, "online", true);
        } else {
            Serial.print("failed, rc=");
            Serial.print(mqttClient.state());
            Serial.println(" retrying in 5 seconds");
            delay(5000);
        }
    }
}

void setup() {
    Serial.begin(115200);
    Serial.println("\n--- Ustaad ESP32 Sensor Node (UNTESTED) ---");

    // Topic string formatting
    snprintf(topic_env, sizeof(topic_env), TOPIC_ENV, SITE, MACHINE_ID);
    snprintf(topic_status, sizeof(topic_status), TOPIC_STATUS, SITE, MACHINE_ID);

    // Pin configurations
    pinMode(MIC_DO_PIN, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(MIC_DO_PIN), on_mic_spike_isr, FALLING);

    pinMode(GAS_ADC_PIN, INPUT);
    pinMode(LDR_PIN, INPUT);

    dht.begin();

    setup_wifi();
    mqttClient.setServer(MQTT_HOST, MQTT_PORT);
}

void loop() {
    if (!mqttClient.connected()) {
        reconnect_mqtt();
    }
    mqttClient.loop();

    unsigned long now = millis();
    if (now - last_publish_ms >= GAS_PUBLISH_INTERVAL_MS) {
        last_publish_ms = now;

        // Atomically snapshot and reset interrupt spike count
        noInterrupts();
        uint32_t noise_count = isr_noise_spikes;
        isr_noise_spikes = 0;
        interrupts();

        // Read physical sensors
        float temp = dht.readTemperature();
        float hum = dht.readHumidity();
        if (isnan(temp)) temp = 30.0;
        if (isnan(hum)) hum = 50.0;

        int gas_raw = analogRead(GAS_ADC_PIN);
        int ldr_raw = analogRead(LDR_PIN);
        bool door_open = (ldr_raw > DOOR_OPEN_LDR_THRESHOLD);

        // Timestamp estimate (Unix timestamp if NTP sync available, else epoch 0)
        unsigned long ts = (now / 1000);

        // Build contract JSON line
        char payload[256];
        snprintf(payload, sizeof(payload),
            "{\"ts\":%lu,\"temp_c\":%.1f,\"hum\":%.0f,\"gas_raw\":%d,\"noise\":%u,\"ldr_raw\":%d,\"door_open\":%s}",
            ts, temp, hum, gas_raw, (unsigned int)noise_count, ldr_raw, door_open ? "true" : "false"
        );

        Serial.print("Publish [");
        Serial.print(topic_env);
        Serial.print("]: ");
        Serial.println(payload);

        mqttClient.publish(topic_env, payload);
    }
}
