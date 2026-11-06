/*
 * unoq_mcu.ino — Arduino Uno Q MCU & Display Node Skeleton
 *
 * UNTESTED on physical hardware — requires Arduino Uno Q board with Linux bridge,
 * MFRC522 SPI RFID reader, TFT SPI display, and 0.96" I2C SSD1306 OLED.
 *
 * Architecture & Responsibilities:
 *  1. MFRC522 RFID Reader:
 *     Detects technician badge tap. Maps card UID to worker ID (e.g., "W-07").
 *     Emits JSON event to Linux bridge: {"type":"badge","worker":"W-07"}
 *  2. 0.96" I2C OLED (SSD1306):
 *     Compact always-on status bar showing [Machine ID] | [Risk Level] | [Worker ID]
 *  3. Color TFT Display (ST7789 / ILI9341):
 *     State machine rendering the 6 contract screens:
 *       - SCREEN_IDLE: Nominal operational status
 *       - SCREEN_ALERT: Anomaly detected with recalled advice
 *       - SCREEN_BADGE: Prompts technician to tap badge to unlock reset
 *       - SCREEN_FIX_SELECT: Visual buttons for 5 fix options:
 *           ["Lubricated", "Cleared blockage", "Replaced part", "Tightened mount", "Other"]
 *       - SCREEN_VERIFYING: Post-reset countdown timer
 *       - SCREEN_RESULT: Final outcome (WORKED in green, FAILED in red)
 *  4. UI Event Dispatch:
 *     Emits JSON messages to agent:
 *       {"type":"badge","worker":"W-07"}
 *       {"type":"fix","fix":"Lubricated"}
 *       {"type":"reset"}
 *
 * NOTE REGARDING UNO Q MCU <-> LINUX BRIDGE:
 *  TODO: The inter-processor bridge on Arduino Uno Q relies on the official
 *  Bridge / RPC library provided by Arduino for heterogeneous Linux+MCU SoCs.
 *  Do NOT invent a proprietary serial framing protocol here. Once the official
 *  Uno Q documentation is released, replace the `bridge_send()` and `bridge_poll()`
 *  placeholders below with the sanctioned Arduino Uno Q RPC bridge calls.
 */

#include <SPI.h>
#include <Wire.h>

// ── Screen State Enumeration (Contract Spec) ───────────────────────────────────
typedef enum {
    SCREEN_IDLE       = 0,
    SCREEN_ALERT      = 1,
    SCREEN_BADGE      = 2,
    SCREEN_FIX_SELECT = 3,
    SCREEN_VERIFYING  = 4,
    SCREEN_RESULT     = 5,
} ScreenState;

static ScreenState g_current_screen = SCREEN_IDLE;
static char g_worker_id[16]         = "NONE";
static char g_risk_level[16]        = "LOW";
static char g_machine_id[16]        = "Pump-2";
static char g_display_title[32]     = "OPERATIONAL";
static char g_display_body[128]     = "All systems nominal.";
static int  g_countdown_s           = 0;

// Fix options contract (exactly these 5 options)
const char* FIX_OPTIONS[5] = {
    "Lubricated",
    "Cleared blockage",
    "Replaced part",
    "Tightened mount",
    "Other"
};

// ── Bridge Communication Stubs ────────────────────────────────────────────────
// TODO: Replace with official Arduino Uno Q Linux Bridge API

void bridge_send_event(const char* json_str) {
    // Sends ui_event to the Linux agent
    Serial.print("[UNO_Q -> AGENT]: ");
    Serial.println(json_str);
}

void bridge_poll_display_commands() {
    // TODO: Read incoming JSON from Linux bridge:
    // {"screen":"alert|badge|fix_select|verifying|result|idle","title":"...","body":"...","risk":"LOW|MED|HIGH","worker":"W-07"}
    if (Serial.available() > 0) {
        String line = Serial.readStringUntil('\n');
        line.trim();
        // Placeholder parsing logic:
        // In production, use ArduinoJson to deserialize and update g_current_screen,
        // g_display_title, g_display_body, g_risk_level, and g_countdown_s.
    }
}

// ── RFID Handler ──────────────────────────────────────────────────────────────

void poll_rfid() {
    // TODO: Initialise and poll MFRC522:
    // if (!mfrc522.PICC_IsNewCardPresent() || !mfrc522.PICC_ReadCardSerial()) return;
    // Map UID bytes to technician badge (e.g., UID [0xDE, 0xAD, 0xBE, 0xEF] -> "W-07")
    //
    // Simulated trigger example:
    // snprintf(g_worker_id, sizeof(g_worker_id), "W-07");
    // bridge_send_event("{\"type\":\"badge\",\"worker\":\"W-07\"}");
}

// ── Display Rendering Functions ───────────────────────────────────────────────

void render_oled_status() {
    // Top status bar: [Pump-2] | Risk: LOW | W: W-07
    // TODO: Draw to 128x64 I2C SSD1306 OLED via Adafruit_SSD1306
}

void render_tft_screen() {
    // Render current screen state on TFT:
    switch (g_current_screen) {
        case SCREEN_IDLE:
            // Background green/dark slate; display title and telemetry summary
            break;
        case SCREEN_ALERT:
            // Background amber/red; show advisory text recalled from memory
            break;
        case SCREEN_BADGE:
            // Prompt technician to tap RFID card to unlock reset
            break;
        case SCREEN_FIX_SELECT:
            // Draw 5 clickable/selectable buttons for FIX_OPTIONS
            break;
        case SCREEN_VERIFYING:
            // Show circular progress bar and countdown seconds remaining
            break;
        case SCREEN_RESULT:
            // Green "WORKED" or Red "FAILED" banner
            break;
    }
}

// ── Arduino Setup and Main Loop ───────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    Serial.println("--- Uno Q MCU Display & RFID Node Initializing (UNTESTED) ---");

    // TODO: Wire.begin(); SPI.begin();
    // TODO: mfrc522.PCD_Init();
    // TODO: tft.init(); oled.begin();

    render_oled_status();
    render_tft_screen();

    // Signal boot event to Linux agent bridge
    bridge_send_event("{\"event\":\"BOOT\",\"device\":\"unoq_mcu\"}");
}

void loop() {
    // 1. Poll RFID reader for badge taps
    poll_rfid();

    // 2. Poll incoming display update commands from Linux host
    bridge_poll_display_commands();

    // 3. Refresh display buffers
    render_oled_status();
    render_tft_screen();

    delay(50);
}
