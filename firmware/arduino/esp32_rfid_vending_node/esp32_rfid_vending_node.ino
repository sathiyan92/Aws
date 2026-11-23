/*
 * ==============================================================================
 * GTECH SMART IOT FLEET PLATFORM
 * Node Type: ESP32 RFID Card-Based Vending Machine Controller
 * File: esp32_rfid_vending_node.ino
 * Firmware: v2.4.0-rfid-tft
 * ==============================================================================
 * Features:
 *   - 3.5" / 4.0" ILI9488 320x480 SPI TFT LCD Display (Vertical Portrait)
 *   - Matches the exact UI design and theme of the QR Vending Machine
 *   - MFRC522 SPI 13.56MHz RFID Reader driver (Shared SPI VSPI bus)
 *   - Supports up to 1,000 users/cards in local ESP32 RAM cache
 *   - Cloud Tap Verification & Dispense Authorization via REST API
 *   - Offline Resilient Vending: Dispenses even when Wi-Fi is lost
 *   - Offline Log Buffering: Syncs vends to cloud when Internet reconnects
 *   - Motor Relay Pulse Control & Buzzer Audio Feedback
 *   - Live Cardholder Name, Quota Remaining, & Real-Time Status Screens
 * ==============================================================================
 * WIRING PINOUT (ESP32 DevKit 30/38-Pin):
 *
 *   SHARED HARDWARE SPI (VSPI):
 *     GPIO 18  ->  SCK  (Shared to MFRC522 SCK & ILI9488 TFT SCK)
 *     GPIO 23  ->  MOSI (Shared to MFRC522 MOSI & ILI9488 TFT SDI/MOSI)
 *     GPIO 19  ->  MISO (To MFRC522 MISO only; TFT does not need MISO)
 *
 *   MFRC522 RFID READER:
 *     GPIO 5   ->  SDA / SS (Dedicated RFID Chip Select)
 *     GPIO 22  ->  RST (RFID Reset)
 *     3.3V     ->  3.3V (Do NOT connect MFRC522 to 5V!)
 *     GND      ->  GND
 *
 *   ILI9488 TFT LCD (320x480 SPI):
 *     GPIO 15  ->  CS (Dedicated TFT Chip Select)
 *     GPIO 4   ->  DC / RS (Data / Command)
 *     GPIO 16  ->  RESET (TFT Reset)
 *     3.3V     ->  VCC (Do NOT connect to 5V!)
 *     3.3V     ->  LED / BL (Backlight Power)
 *     GND      ->  GND
 *
 *   ACTUATORS & INDICATORS:
 *     GPIO 26  ->  Motor Dispense Relay (Active HIGH)
 *     GPIO 27  ->  Piezo Buzzer (Active HIGH)
 *     GPIO 2   ->  Onboard Status LED
 * ==============================================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <MFRC522.h>
#include <ArduinoJson.h>
#include <DIYables_TFT_SPI.h>

// ==============================================================================
// 1. HARDWARE PIN DEFINITIONS
// ==============================================================================

// Shared Hardware SPI Pins (VSPI on ESP32)
#define SPI_SCK_PIN        18    // Hardware SPI Clock
#define SPI_MISO_PIN       19    // Hardware SPI MISO (RFID)
#define SPI_MOSI_PIN       23    // Hardware SPI MOSI (RFID & TFT)

// MFRC522 RFID Dedicated Pins
#define RFID_SS_PIN        5     // Chip Select / SDA
#define RFID_RST_PIN       22    // Reset Pin

// ILI9488 320x480 TFT LCD Dedicated Pins
#define TFT_CS_PIN         15    // TFT Chip Select
#define TFT_DC_PIN         4     // TFT Data / Command
#define TFT_RST_PIN        16    // TFT Reset Pin
#define TFT_WIDTH          320
#define TFT_HEIGHT         480
#define TFT_ROTATION       0     // 0 = Vertical Portrait (320w x 480h)

// Actuators & Indicators
#define PIN_RELAY_MOTOR    26    // Dispense Motor Relay (Active HIGH)
#define PIN_BUZZER         27    // Buzzer (Active HIGH)
#define PIN_STATUS_LED     2     // Onboard Status LED (GPIO 2)

// ==============================================================================
// 2. NETWORK & SERVER CONFIGURATION
// ==============================================================================

const char* WIFI_SSID       = "GTech_Office_2.4G";
const char* WIFI_PASSWORD   = "YourWifiPassword";

// Production Cloud API URL
const char* SERVER_BASE_URL = "http://www.gtechinfo.in";

// Unique Machine Identifier mapped in cloud database
const char* DEVICE_ID       = "VM-000001";

// Default dispense pulse time if cloud doesn't specify (in milliseconds)
const int DEFAULT_DISPENSE_MS = 1500;

// ==============================================================================
// 3. UI COLOR PALETTE (Matches QR Vending Machine Design)
// ==============================================================================

#define COLOR_BG           DIYables_TFT_SPI::colorRGB(11, 17, 32)     // Dark Navy Slate (#0B1120)
#define COLOR_CARD         DIYables_TFT_SPI::colorRGB(26, 36, 56)     // Slate Card (#1A2438)
#define COLOR_CARD_BORDER  DIYables_TFT_SPI::colorRGB(51, 65, 85)     // Slate Border (#334155)
#define COLOR_HEADER       DIYables_TFT_SPI::colorRGB(15, 23, 42)     // Header background
#define COLOR_WHITE        DIYables_TFT_SPI::colorRGB(255, 255, 255)
#define COLOR_BLACK        DIYables_TFT_SPI::colorRGB(0, 0, 0)
#define COLOR_CYAN         DIYables_TFT_SPI::colorRGB(56, 189, 248)   // Sky Blue (#38BDF8)
#define COLOR_BLUE         DIYables_TFT_SPI::colorRGB(59, 130, 246)   // Royal Blue (#3B82F6)
#define COLOR_GREEN        DIYables_TFT_SPI::colorRGB(16, 185, 129)   // Success Green (#10B981)
#define COLOR_RED          DIYables_TFT_SPI::colorRGB(239, 68, 68)    // Danger Red (#EF4444)
#define COLOR_YELLOW       DIYables_TFT_SPI::colorRGB(245, 158, 11)   // Warning Amber (#F59E0B)
#define COLOR_MUTED        DIYables_TFT_SPI::colorRGB(148, 163, 184)  // Slate Muted (#94A3B8)

// ==============================================================================
// 4. SCALE ARCHITECTURE: 1,000 CARDS LOCAL RAM CACHE
// ==============================================================================

#define MAX_CACHED_CARDS 1000

struct RFIDCardCacheItem {
    char uid[12];        // e.g. "A1B2C3D4" (null-terminated)
    char name[20];       // Cardholder name (truncated to 19 chars + null)
    int16_t daily_limit; // Max allowed per day (0 = unlimited)
    int16_t used_today;  // Used count today
};

// Global 1,000-card whitelist memory table (~36 KB in RAM)
RFIDCardCacheItem localCardCache[MAX_CACHED_CARDS];
int totalCachedCards = 0;

// Offline Log Buffer (Holds up to 64 offline vends when internet is down)
#define MAX_OFFLINE_BUFFER 64
struct OfflineVendRecord {
    char uid[12];
    uint32_t timestamp_sec;
    int dispense_ms;
};
OfflineVendRecord offlineBuffer[MAX_OFFLINE_BUFFER];
int offlineBufferCount = 0;

// State flags
bool isWifiConnected = false;
unsigned long lastHeartbeatTime = 0;
unsigned long lastCardSyncTime = 0;
const unsigned long SYNC_INTERVAL_MS = 300000; // Auto-sync whitelist every 5 minutes

// Hardware Driver Objects
DIYables_TFT_SPI tft(TFT_CS_PIN, TFT_DC_PIN, TFT_RST_PIN);
MFRC522 rfid(RFID_SS_PIN, RFID_RST_PIN);

// ==============================================================================
// 5. SPI BUS ARBITRATION HELPERS
// ==============================================================================

void selectTFT() {
    digitalWrite(RFID_SS_PIN, HIGH);  // Deselect RFID reader
    digitalWrite(TFT_CS_PIN, LOW);    // Select TFT LCD
}

void deselectTFT() {
    digitalWrite(TFT_CS_PIN, HIGH);   // Deselect TFT LCD
}

void selectRFID() {
    digitalWrite(TFT_CS_PIN, HIGH);   // Deselect TFT LCD
    digitalWrite(RFID_SS_PIN, LOW);   // Select RFID reader
}

void deselectRFID() {
    digitalWrite(RFID_SS_PIN, HIGH);  // Deselect RFID reader
}

// ==============================================================================
// 6. BUZZER AUDIO FEEDBACK HELPER
// ==============================================================================

void beep(int frequency, int duration_ms) {
    digitalWrite(PIN_BUZZER, HIGH);
    delay(duration_ms);
    digitalWrite(PIN_BUZZER, LOW);
}

void playSuccessTone() {
    beep(2000, 100);
    delay(50);
    beep(2500, 150);
}

void playErrorTone() {
    for (int i = 0; i < 3; i++) {
        beep(1000, 80);
        delay(60);
    }
}

void playWarningTone() {
    beep(1500, 200);
    delay(100);
    beep(1500, 200);
}

// ==============================================================================
// 7. TFT LCD UI DRAWING FUNCTIONS
// ==============================================================================

void uiDrawBootScreen() {
    selectTFT();
    tft.fillScreen(COLOR_BG);

    // Header Card
    tft.fillRect(10, 30, 300, 90, COLOR_CARD);
    tft.drawRect(10, 30, 300, 90, COLOR_CYAN);
    tft.setCursor(30, 50);
    tft.setTextColor(COLOR_CYAN);
    tft.setTextSize(2);
    tft.print("G-TECH SMART FLEET");
    tft.setCursor(40, 85);
    tft.setTextColor(COLOR_WHITE);
    tft.setTextSize(2);
    tft.print("RFID VENDING NODE");

    // Center Info Card
    tft.fillRect(10, 140, 300, 240, COLOR_CARD);
    tft.drawRect(10, 140, 300, 240, COLOR_CARD_BORDER);

    tft.setCursor(30, 170);
    tft.setTextColor(COLOR_YELLOW);
    tft.setTextSize(2);
    tft.print("INITIALIZING...");

    tft.setCursor(30, 220);
    tft.setTextColor(COLOR_WHITE);
    tft.setTextSize(1);
    tft.print("Machine ID    : ");
    tft.setTextColor(COLOR_CYAN);
    tft.println(DEVICE_ID);

    tft.setCursor(30, 245);
    tft.setTextColor(COLOR_WHITE);
    tft.print("Firmware      : v2.4.0-rfid-tft");

    tft.setCursor(30, 270);
    tft.print("Capacity      : 1,000 Cards Cache");

    tft.setCursor(30, 295);
    tft.print("Display       : ILI9488 320x480 SPI");

    tft.setCursor(30, 320);
    tft.print("Reader        : MFRC522 13.56MHz");

    // Footer
    tft.setCursor(45, 430);
    tft.setTextColor(COLOR_MUTED);
    tft.setTextSize(1);
    tft.print("Connecting to G-TECH Cloud...");

    deselectTFT();
}

void uiDrawWiFiConnectingScreen(const char* ssid) {
    selectTFT();
    tft.fillRect(15, 380, 290, 70, COLOR_BG);
    tft.fillRect(15, 380, 290, 70, COLOR_CARD);
    tft.drawRect(15, 380, 290, 70, COLOR_BLUE);

    tft.setCursor(30, 395);
    tft.setTextColor(COLOR_CYAN);
    tft.setTextSize(1);
    tft.print("Connecting to Wi-Fi:");

    tft.setCursor(30, 420);
    tft.setTextColor(COLOR_WHITE);
    tft.setTextSize(2);
    tft.print(ssid);

    deselectTFT();
}

void uiDrawStandbyScreen() {
    selectTFT();
    tft.fillScreen(COLOR_BG);

    // Top Header Banner
    tft.fillRect(0, 0, TFT_WIDTH, 55, COLOR_HEADER);
    tft.drawFastHLine(0, 55, TFT_WIDTH, COLOR_CARD_BORDER);

    tft.setCursor(20, 18);
    tft.setTextColor(COLOR_CYAN);
    tft.setTextSize(2);
    tft.print("G-TECH");

    tft.setCursor(105, 18);
    tft.setTextColor(COLOR_WHITE);
    tft.setTextSize(2);
    tft.print("SMART VEND");

    // Network Status Pill on Header
    if (WiFi.status() == WL_CONNECTED) {
        tft.fillRoundRect(240, 12, 68, 30, 6, COLOR_GREEN);
        tft.setCursor(248, 20);
        tft.setTextColor(COLOR_BLACK);
        tft.setTextSize(1);
        tft.print("ONLINE");
    } else {
        tft.fillRoundRect(235, 12, 75, 30, 6, COLOR_YELLOW);
        tft.setCursor(242, 20);
        tft.setTextColor(COLOR_BLACK);
        tft.setTextSize(1);
        tft.print("OFFLINE");
    }

    // Machine ID Sub-bar
    tft.fillRect(0, 56, TFT_WIDTH, 28, COLOR_CARD);
    tft.setCursor(20, 64);
    tft.setTextColor(COLOR_MUTED);
    tft.setTextSize(1);
    tft.printf("NODE: %s  |  MODE: RFID CARD TAP", DEVICE_ID);

    // Center Hero Card
    tft.fillRoundRect(16, 100, 288, 280, 12, COLOR_CARD);
    tft.drawRoundRect(16, 100, 288, 280, 12, COLOR_CYAN);

    // Decorative Icon / Box
    tft.fillRoundRect(115, 125, 90, 60, 8, COLOR_BG);
    tft.drawRoundRect(115, 125, 90, 60, 8, COLOR_CYAN);
    tft.setCursor(130, 145);
    tft.setTextColor(COLOR_CYAN);
    tft.setTextSize(2);
    tft.print("RFID");

    tft.setCursor(48, 210);
    tft.setTextColor(COLOR_WHITE);
    tft.setTextSize(2);
    tft.print("PLEASE TAP YOUR");

    tft.setCursor(55, 245);
    tft.setTextColor(COLOR_GREEN);
    tft.setTextSize(3);
    tft.print("ID CARD");

    tft.setCursor(42, 295);
    tft.setTextColor(COLOR_CYAN);
    tft.setTextSize(2);
    tft.print("TO DISPENSE ITEM");

    tft.setCursor(35, 345);
    tft.setTextColor(COLOR_MUTED);
    tft.setTextSize(1);
    tft.print("Hold card flat against reader (1-2s)");

    // Bottom Status Pill Card
    tft.fillRoundRect(16, 395, 288, 65, 8, COLOR_CARD);
    tft.drawRoundRect(16, 395, 288, 65, 8, COLOR_CARD_BORDER);

    tft.setCursor(30, 412);
    if (WiFi.status() == WL_CONNECTED) {
        tft.setTextColor(COLOR_GREEN);
        tft.setTextSize(1);
        tft.printf("* Cloud Connected  |  IP: %s", WiFi.localIP().toString().c_str());
    } else {
        tft.setTextColor(COLOR_YELLOW);
        tft.setTextSize(1);
        tft.print("* Offline Mode Active  |  Local Cache Ready");
    }

    tft.setCursor(30, 435);
    tft.setTextColor(COLOR_MUTED);
    tft.setTextSize(1);
    tft.printf("Authorized Cards Cached: %d / 1,000", totalCachedCards);

    deselectTFT();
}

void uiDrawVerifyingScreen(const char* uid) {
    selectTFT();

    // Overwrite Hero card with Verifying state
    tft.fillRoundRect(16, 100, 288, 280, 12, COLOR_CARD);
    tft.drawRoundRect(16, 100, 288, 280, 12, COLOR_YELLOW);

    tft.setCursor(55, 145);
    tft.setTextColor(COLOR_YELLOW);
    tft.setTextSize(3);
    tft.print("VERIFYING");

    tft.setCursor(65, 195);
    tft.setTextColor(COLOR_WHITE);
    tft.setTextSize(2);
    tft.print("Card UID:");

    tft.setCursor(75, 230);
    tft.setTextColor(COLOR_CYAN);
    tft.setTextSize(2);
    tft.print(uid);

    tft.setCursor(40, 285);
    tft.setTextColor(COLOR_MUTED);
    tft.setTextSize(1);
    tft.print("Checking authorization quota...");

    tft.fillRect(40, 315, 240, 12, COLOR_BG);
    tft.fillRoundRect(40, 315, 160, 12, 4, COLOR_YELLOW);

    deselectTFT();
}

void uiDrawDispenseScreen(const char* name, int used, int limit, int pulse_ms) {
    selectTFT();

    // Success Green Card
    tft.fillRoundRect(16, 100, 288, 280, 12, COLOR_CARD);
    tft.drawRoundRect(16, 100, 288, 280, 12, COLOR_GREEN);

    // Green Header Tag
    tft.fillRoundRect(30, 120, 260, 45, 6, COLOR_GREEN);
    tft.setCursor(45, 132);
    tft.setTextColor(COLOR_BLACK);
    tft.setTextSize(2);
    tft.print("ACCESS GRANTED!");

    tft.setCursor(30, 185);
    tft.setTextColor(COLOR_WHITE);
    tft.setTextSize(2);
    tft.print("Welcome,");

    tft.setCursor(30, 215);
    tft.setTextColor(COLOR_CYAN);
    tft.setTextSize(2);
    tft.print(name);

    // Quota Counter
    tft.setCursor(30, 255);
    tft.setTextColor(COLOR_MUTED);
    tft.setTextSize(1);
    if (limit <= 0) {
        tft.print("Today's Allowance: Unlimited");
    } else {
        tft.printf("Today's Allowance: %d of %d Used", used, limit);
    }

    // Action banner
    tft.fillRoundRect(30, 290, 260, 65, 6, COLOR_BG);
    tft.drawRoundRect(30, 290, 260, 65, 6, COLOR_GREEN);

    tft.setCursor(45, 305);
    tft.setTextColor(COLOR_GREEN);
    tft.setTextSize(2);
    tft.print("DISPENSING ITEM");

    tft.setCursor(65, 332);
    tft.setTextColor(COLOR_MUTED);
    tft.setTextSize(1);
    tft.print("Please collect product below");

    deselectTFT();
}

void uiDrawDeniedScreen(const char* header, const char* reason) {
    selectTFT();

    // Red Danger Card
    tft.fillRoundRect(16, 100, 288, 280, 12, COLOR_CARD);
    tft.drawRoundRect(16, 100, 288, 280, 12, COLOR_RED);

    // Red Tag
    tft.fillRoundRect(30, 120, 260, 45, 6, COLOR_RED);
    tft.setCursor(55, 132);
    tft.setTextColor(COLOR_WHITE);
    tft.setTextSize(2);
    tft.print("ACCESS DENIED");

    tft.setCursor(30, 195);
    tft.setTextColor(COLOR_YELLOW);
    tft.setTextSize(2);
    tft.print(header);

    tft.setCursor(30, 235);
    tft.setTextColor(COLOR_WHITE);
    tft.setTextSize(2);
    tft.print(reason);

    tft.setCursor(30, 295);
    tft.setTextColor(COLOR_MUTED);
    tft.setTextSize(1);
    tft.print("Please contact platform administrator.");

    tft.setCursor(30, 320);
    tft.print("Support: info.gtech2016@gmail.com");

    deselectTFT();
}

void uiDrawVendCompleteScreen() {
    selectTFT();

    tft.fillRoundRect(30, 290, 260, 65, 6, COLOR_GREEN);
    tft.setCursor(60, 312);
    tft.setTextColor(COLOR_BLACK);
    tft.setTextSize(2);
    tft.print("THANK YOU!");

    deselectTFT();
}

// ==============================================================================
// 8. MOTOR RELAY CONTROL
// ==============================================================================

void triggerDispenseMotor(int pulse_ms) {
    Serial.printf("[VEND] Activating Relay Motor for %d ms...\n", pulse_ms);
    digitalWrite(PIN_STATUS_LED, HIGH);
    digitalWrite(PIN_RELAY_MOTOR, HIGH);  // Energize motor relay
    delay(pulse_ms);
    digitalWrite(PIN_RELAY_MOTOR, LOW);   // De-energize
    digitalWrite(PIN_STATUS_LED, LOW);
    Serial.println("[VEND] Dispense Complete.");

    uiDrawVendCompleteScreen();
    delay(1200);
    uiDrawStandbyScreen();
}

// ==============================================================================
// 9. CACHE MANAGEMENT FUNCTIONS (1,000 Cards)
// ==============================================================================

int findCardInCache(const char* uid) {
    for (int i = 0; i < totalCachedCards; i++) {
        if (strcasecmp(localCardCache[i].uid, uid) == 0) {
            return i;
        }
    }
    return -1; // Not found
}

void syncWhitelistFromCloud() {
    if (WiFi.status() != WL_CONNECTED) return;

    Serial.println("[SYNC] Requesting 1,000-card whitelist from Cloud...");
    HTTPClient http;
    String url = String(SERVER_BASE_URL) + "/api/v1/rfid-vending/devices/" + String(DEVICE_ID) + "/sync-cards";
    
    http.begin(url);
    http.setTimeout(10000);
    int httpCode = http.GET();

    if (httpCode == HTTP_CODE_OK) {
        String payload = http.getString();
        
        // Parse JSON with DynamicJsonDocument scaled for up to 1000 items
        DynamicJsonDocument doc(49152); // 48 KB json buffer
        DeserializationError err = deserializeJson(doc, payload);

        if (!err) {
            JsonArray cards = doc["cards"].as<JsonArray>();
            totalCachedCards = 0;

            for (JsonObject c : cards) {
                if (totalCachedCards >= MAX_CACHED_CARDS) break;

                const char* u = c["uid"] | "";
                const char* n = c["name"] | "Cardholder";
                int limit = c["limit"] | 1;
                int used = c["used"] | 0;

                strncpy(localCardCache[totalCachedCards].uid, u, sizeof(localCardCache[0].uid) - 1);
                localCardCache[totalCachedCards].uid[sizeof(localCardCache[0].uid) - 1] = '\0';

                strncpy(localCardCache[totalCachedCards].name, n, sizeof(localCardCache[0].name) - 1);
                localCardCache[totalCachedCards].name[sizeof(localCardCache[0].name) - 1] = '\0';

                localCardCache[totalCachedCards].daily_limit = limit;
                localCardCache[totalCachedCards].used_today = used;

                totalCachedCards++;
            }

            Serial.printf("[SYNC] * Success! Loaded %d authorized cards into ESP32 RAM cache.\n", totalCachedCards);
            uiDrawStandbyScreen();
        } else {
            Serial.printf("[SYNC] JSON parse error: %s\n", err.c_str());
        }
    } else {
        Serial.printf("[SYNC] HTTP error: %d\n", httpCode);
    }
    http.end();
}

void flushOfflineBufferToCloud() {
    if (offlineBufferCount == 0 || WiFi.status() != WL_CONNECTED) return;

    Serial.printf("[OFFLINE] Flushing %d buffered offline vends to Cloud...\n", offlineBufferCount);
    HTTPClient http;
    String url = String(SERVER_BASE_URL) + "/api/v1/rfid-vending/offline-sync";

    DynamicJsonDocument doc(4096);
    doc["device_id"] = DEVICE_ID;
    JsonArray logs = doc.createNestedArray("logs");

    for (int i = 0; i < offlineBufferCount; i++) {
        JsonObject item = logs.createNestedObject();
        item["card_uid"] = offlineBuffer[i].uid;
        item["dispense_ms"] = offlineBuffer[i].dispense_ms;
    }

    String requestBody;
    serializeJson(doc, requestBody);

    http.begin(url);
    http.addHeader("Content-Type", "application/json");
    int httpCode = http.POST(requestBody);

    if (httpCode == HTTP_CODE_OK || httpCode == 201) {
        Serial.println("[OFFLINE] * Buffer successfully synced to Cloud database!");
        offlineBufferCount = 0; // Clear buffer
    } else {
        Serial.printf("[OFFLINE] Sync failed with status: %d\n", httpCode);
    }
    http.end();
}

// ==============================================================================
// 10. CARD TAP PROCESSOR (ONLINE & OFFLINE)
// ==============================================================================

void processOfflineTap(const char* uid) {
    int idx = findCardInCache(uid);

    if (idx >= 0) {
        RFIDCardCacheItem& item = localCardCache[idx];

        // Check local quota
        if (item.daily_limit <= 0 || item.used_today < item.daily_limit) {
            item.used_today++;
            Serial.printf("[OFFLINE VEND] * Card Authorized! Welcome %s (Used: %d/%d)\n", 
                          item.name, item.used_today, item.daily_limit);
            playSuccessTone();
            uiDrawDispenseScreen(item.name, item.used_today, item.daily_limit, DEFAULT_DISPENSE_MS);
            triggerDispenseMotor(DEFAULT_DISPENSE_MS);

            // Buffer offline vend
            if (offlineBufferCount < MAX_OFFLINE_BUFFER) {
                strncpy(offlineBuffer[offlineBufferCount].uid, uid, sizeof(offlineBuffer[0].uid) - 1);
                offlineBuffer[offlineBufferCount].timestamp_sec = millis() / 1000;
                offlineBuffer[offlineBufferCount].dispense_ms = DEFAULT_DISPENSE_MS;
                offlineBufferCount++;
                Serial.printf("[OFFLINE] Buffered offline event (%d/%d queued)\n", offlineBufferCount, MAX_OFFLINE_BUFFER);
            }
        } else {
            Serial.printf("[OFFLINE VEND] ! Daily Limit Reached for %s (%d/%d)\n", 
                          item.name, item.used_today, item.daily_limit);
            playWarningTone();
            uiDrawDeniedScreen("DAILY QUOTA EXCEEDED", "Allowance Used Up");
            delay(2500);
            uiDrawStandbyScreen();
        }
    } else {
        Serial.println("[OFFLINE VEND] ! Card not in local whitelist. Access Denied.");
        playErrorTone();
        uiDrawDeniedScreen("CARD UNREGISTERED", "Not in Whitelist");
        delay(2500);
        uiDrawStandbyScreen();
    }
}

void processCardTap(const char* uid) {
    Serial.println("\n------------------------------------------------");
    Serial.printf("[TAP] Card Detected! UID: %s\n", uid);

    beep(2500, 80); // Quick chirp acknowledgement
    uiDrawVerifyingScreen(uid);

    // ----------------------------------------------------
    // SCENARIO 1: ONLINE MODE (Wi-Fi Connected)
    // ----------------------------------------------------
    if (WiFi.status() == WL_CONNECTED) {
        Serial.println("[ONLINE] Contacting Cloud Backend for verification...");

        HTTPClient http;
        String url = String(SERVER_BASE_URL) + "/api/v1/rfid-vending/verify-tap";
        http.begin(url);
        http.addHeader("Content-Type", "application/json");
        http.setTimeout(4000);

        StaticJsonDocument<256> doc;
        doc["device_id"] = DEVICE_ID;
        doc["card_uid"] = uid;
        doc["pulse_ms"] = DEFAULT_DISPENSE_MS;

        String requestBody;
        serializeJson(doc, requestBody);

        int httpCode = http.POST(requestBody);

        if (httpCode == HTTP_CODE_OK) {
            String responseStr = http.getString();
            StaticJsonDocument<512> resp;
            deserializeJson(resp, responseStr);

            bool authorized = resp["authorized"] | false;
            const char* status = resp["status"] | "UNKNOWN";
            const char* username = resp["username"] | "User";
            const char* msg = resp["message"] | "";
            int pulse = resp["dispense_pulse_ms"] | DEFAULT_DISPENSE_MS;
            int used = resp["used_today"] | 0;
            int limit = resp["daily_limit"] | 1;

            if (authorized && strcmp(status, "DISPENSED_SUCCESS") == 0) {
                Serial.printf("[VERIFY] * ACCESS GRANTED! Welcome %s (%d/%d)\n", username, used, limit);
                playSuccessTone();
                uiDrawDispenseScreen(username, used, limit, pulse);
                triggerDispenseMotor(pulse);
            } else if (strcmp(status, "DAILY_LIMIT_EXCEEDED") == 0) {
                Serial.printf("[VERIFY] ! QUOTA EXCEEDED! Limit: %d reached for %s\n", limit, username);
                playWarningTone();
                uiDrawDeniedScreen("DAILY LIMIT EXCEEDED", "No Vends Remaining");
                delay(2500);
                uiDrawStandbyScreen();
            } else if (strcmp(status, "BLOCKED_CARD") == 0) {
                Serial.printf("[VERIFY] ! CARD BLOCKED: %s is suspended\n", username);
                playErrorTone();
                uiDrawDeniedScreen("CARD BLOCKED", "Account Suspended");
                delay(2500);
                uiDrawStandbyScreen();
            } else {
                Serial.printf("[VERIFY] ! REJECTED: %s\n", msg);
                playErrorTone();
                uiDrawDeniedScreen("ACCESS REJECTED", msg[0] ? msg : "Card Invalid");
                delay(2500);
                uiDrawStandbyScreen();
            }
        } else {
            Serial.printf("[ONLINE] Cloud HTTP timeout or error: %d. Falling back to Local Cache!\n", httpCode);
            processOfflineTap(uid);
        }
        http.end();
    }
    // ----------------------------------------------------
    // SCENARIO 2: OFFLINE MODE (No Wi-Fi / Local Fallback)
    // ----------------------------------------------------
    else {
        Serial.println("[OFFLINE MODE] Verifying against local 1,000-card RAM cache...");
        processOfflineTap(uid);
    }
    Serial.println("------------------------------------------------\n");
}

// ==============================================================================
// 11. SETUP & INITIALIZATION
// ==============================================================================

void setup() {
    // 1. Critical Boot Glitch Protection: Clamp Motor Relay to OFF immediately
    pinMode(PIN_RELAY_MOTOR, OUTPUT);
    digitalWrite(PIN_RELAY_MOTOR, LOW); // Relay strictly OFF

    pinMode(PIN_BUZZER, OUTPUT);
    digitalWrite(PIN_BUZZER, LOW);

    pinMode(PIN_STATUS_LED, OUTPUT);
    digitalWrite(PIN_STATUS_LED, LOW);

    // Setup Chip Select pins to inactive (HIGH)
    pinMode(RFID_SS_PIN, OUTPUT);
    digitalWrite(RFID_SS_PIN, HIGH);

    pinMode(TFT_CS_PIN, OUTPUT);
    digitalWrite(TFT_CS_PIN, HIGH);

    Serial.begin(115200);
    delay(200);

    Serial.println("\n==============================================");
    Serial.println("   GTECH ESP32 RFID VENDING CONTROLLER NODE   ");
    Serial.println("   Capacity: 1,000 Users / ILI9488 TFT LCD    ");
    Serial.println("==============================================");

    // Initial audio chirp
    beep(2000, 100);

    // 2. Initialize Hardware SPI Bus
    SPI.begin(SPI_SCK_PIN, SPI_MISO_PIN, SPI_MOSI_PIN, RFID_SS_PIN);

    // 3. Initialize ILI9488 TFT LCD Display
    Serial.println("[TFT] Initializing 320x480 ILI9488 SPI LCD Display...");
    selectTFT();
    tft.begin();
    tft.setRotation(TFT_ROTATION); // Vertical Portrait
    deselectTFT();

    // Show initial boot animation screen
    uiDrawBootScreen();
    delay(1200);

    // 4. Initialize MFRC522 RFID reader
    selectRFID();
    rfid.PCD_Init();
    delay(50);
    byte v = rfid.PCD_ReadRegister(rfid.VersionReg);
    deselectRFID();

    Serial.printf("[RFID] MFRC522 Version: 0x%02X\n", v);
    if (v == 0x00 || v == 0xFF) {
        Serial.println("[RFID] ! WARNING: MFRC522 reader communication failed! Check wiring.");
    } else {
        Serial.println("[RFID] * MFRC522 RFID Reader successfully initialized!");
    }

    // 5. Connect to Wi-Fi
    uiDrawWiFiConnectingScreen(WIFI_SSID);
    Serial.printf("[WIFI] Connecting to '%s'...\n", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 20) {
        delay(500);
        Serial.print(".");
        attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        isWifiConnected = true;
        Serial.printf("\n[WIFI] * Connected! IP: %s\n", WiFi.localIP().toString().c_str());
        playSuccessTone();

        // Initial whitelist download
        syncWhitelistFromCloud();
    } else {
        Serial.println("\n[WIFI] ! Wi-Fi Connection Failed. Running in OFFLINE CACHE MODE.");
        playWarningTone();
    }

    // Draw main operational standby screen
    uiDrawStandbyScreen();
    Serial.println("\n[READY] Vending Machine is Ready. Tap an RFID card to vend!\n");
}

// ==============================================================================
// 12. MAIN LOOP
// ==============================================================================

void loop() {
    unsigned long currentMillis = millis();

    // 1. Maintain Wi-Fi and auto-sync
    if (WiFi.status() == WL_CONNECTED) {
        if (!isWifiConnected) {
            isWifiConnected = true;
            Serial.println("[WIFI] * Reconnected to Internet!");
            playSuccessTone();
            uiDrawStandbyScreen();
            flushOfflineBufferToCloud();
            syncWhitelistFromCloud();
        }

        // Periodic sync every 5 minutes
        if (currentMillis - lastCardSyncTime > SYNC_INTERVAL_MS) {
            lastCardSyncTime = currentMillis;
            syncWhitelistFromCloud();
            flushOfflineBufferToCloud();
        }
    } else {
        if (isWifiConnected) {
            isWifiConnected = false;
            Serial.println("[WIFI] ! Lost Internet Connection! Switching to Offline Mode.");
            uiDrawStandbyScreen();
        }
    }

    // 2. Check for RFID Card Tap
    selectRFID();
    bool newCard = rfid.PICC_IsNewCardPresent();
    if (!newCard) {
        deselectRFID();
        delay(40);
        return;
    }

    bool readSuccess = rfid.PICC_ReadCardSerial();
    if (!readSuccess) {
        deselectRFID();
        delay(40);
        return;
    }

    // Convert UID bytes to Hex string
    char uidString[16] = {0};
    for (byte i = 0; i < rfid.uid.size && i < 7; i++) {
        char byteHex[4];
        sprintf(byteHex, "%02X", rfid.uid.uidByte[i]);
        strcat(uidString, byteHex);
    }

    // Halt PICC and stop encryption on PCD
    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();
    deselectRFID();

    // Process the tapped card with full TFT display feedback
    processCardTap(uidString);

    // Debounce pause so single tap doesn't double-trigger
    delay(1000);
}
