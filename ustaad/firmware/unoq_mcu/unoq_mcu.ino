/*
 * unoq_mcu.ino — Uno Q MCU Skeleton
 *
 * UNTESTED — requires Uno Q hardware and official MCU-Linux Bridge API.
 *
 * Responsibilities:
 *   - MFRC522 RFID reader → badge-in events (ui_event MQTT: type=badge)
 *   - TFT display state machine (6 screens: idle, alert, badge, fix_select,
 *     verifying, result)
 *   - 0.96" OLED status bar (machine id, risk level, worker id)
 *   - Receives "display" MQTT messages from agent
 *   - Emits "ui_event" MQTT messages (badge, fix, reset) to agent
 *
 * TODO: Read the official Uno Q MCU<->Linux Bridge API documentation before
 *       implementing serial/USB communication.  The API for passing data between
 *       this sketch and the Linux-side agent is NOT guessed here — it must be
 *       sourced from official Uno Q docs.
 */

// ── Placeholder includes (verify library names for Uno Q board) ──────────────
// #include <SPI.h>
// #include <MFRC522.h>
// #include <TFT_eSPI.h>       // or Adafruit_GFX + driver for your TFT
// #include <Adafruit_SSD1306.h>

// ── Screen states ─────────────────────────────────────────────────────────────
typedef enum {
    SCREEN_IDLE       = 0,
    SCREEN_ALERT      = 1,
    SCREEN_BADGE      = 2,
    SCREEN_FIX_SELECT = 3,
    SCREEN_VERIFYING  = 4,
    SCREEN_RESULT     = 5,
} ScreenState;

static ScreenState current_screen = SCREEN_IDLE;

void setup() {
    Serial.begin(115200);
    // TODO: Initialise MFRC522, TFT, OLED
    // TODO: Connect to Uno Q MCU<->Linux Bridge (see official API docs)
    Serial.println("{\"event\":\"BOOT\",\"device\":\"unoq_mcu\"}");
}

void loop() {
    // TODO: Poll RFID reader
    // TODO: Poll for display commands from Linux bridge
    // TODO: Update TFT / OLED based on current_screen
    delay(100);
}

/*
 * Fix options the agent can send (must match agent/models.py):
 *   "Lubricated"
 *   "Cleared blockage"
 *   "Replaced part"
 *   "Tightened mount"
 *   "Other"
 *
 * TODO: Render these as buttons on SCREEN_FIX_SELECT and emit:
 *   {"type":"fix","fix":"Lubricated"} via the MCU<->Linux Bridge.
 */

