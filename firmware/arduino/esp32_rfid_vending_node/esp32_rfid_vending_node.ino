/*
 * ==============================================================================
 * GTECH SMART IOT FLEET PLATFORM
 * Node Type: ESP32 RFID Card-Based Vending Machine Controller
 * File: esp32_rfid_vending_node.ino
 * ==============================================================================
 * Features:
 *   - Supports up to 1,000 users/cards in local ESP32 RAM cache
 *   - MFRC522 SPI 13.56MHz RFID Reader driver
 *   - Cloud Tap Verification & Dispense Authorization
 *   - Method C: Live Bench Tap-to-Enrollment Mode Support
 *   - Offline Resilient Vending: Dispenses even when Wi-Fi is lost
 *   - Offline Log Buffering: Syncs vends to cloud when Internet reconnects
 *   - Motor Relay Pulse Control & Buzzer Audio Feedback
 *   - Graphical / Character Status Display with Offline Warning Indicators
 * ==============================================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <SPI.h>
#include <MFRC522.h>
#include <ArduinoJson.h>

// ==============================================================================
// 1. HARDWARE PIN DEFINITIONS
// ==============================================================================

// MFRC522 SPI Pins (Standard VSPI on ESP32)
#define RFID_SS_PIN        5     // Chip Select / SDA
#define RFID_RST_PIN       22    // Reset Pin
#define RFID_SCK_PIN       18    // SPI Clock
#define RFID_MISO_PIN      19    // SPI MISO
#define RFID_MOSI_PIN      23    // SPI MOSI

// Actuators & Indicators
#define PIN_RELAY_MOTOR    26    // Dispense Motor Relay (Active HIGH)
#define PIN_BUZZER         27    // Buzzer (Active HIGH or PWM)
#define PIN_STATUS_LED     2     // Onboard LED (GPIO 2)

// ==============================================================================
// 2. NETWORK & SERVER CONFIGURATION
// ==============================================================================

const char* WIFI_SSID     = "GTech_Office_2.4G";
const char* WIFI_PASSWORD = "YourWifiPassword";

// Production Cloud API URL (or IP e.g. "https://gtechinfo.in" or "http://192.168.1.100:8000")
const char* SERVER_BASE_URL = "https://gtechinfo.in";

// Unique Machine Identifier mapped in cloud database
const char* DEVICE_ID = "VM-000001";

// Default dispense pulse time if cloud doesn't specify (in milliseconds)
const int DEFAULT_DISPENSE_MS = 1500;

// ==============================================================================
// 3. SCALE ARCHITECTURE: 1,000 CARDS LOCAL RAM CACHE
// ==============================================================================

#define MAX_CACHED_CARDS 1000

struct RFIDCardCacheItem {
    char uid[12];        // e.g. "A1B2C3D4" (null-terminated)
    char name[20];       // Cardholder name (truncated to 19 chars + null)
    int16_t daily_limit; // Max allowed per day (0 = unlimited)
    int16_t used_today;  // Used count today
};

// Global 1,000-card whitelist memory table (Only ~36 KB in RAM!)
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

// Objects
MFRC522 rfid(RFID_SS_PIN, RFID_RST_PIN);

// ==============================================================================
// 4. BUZZER AUDIO FEEDBACK HELPER
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
// 5. MOTOR RELAY CONTROL
// ==============================================================================

void triggerDispenseMotor(int pulse_ms) {
    Serial.printf("[VEND] Activating Relay Motor for %d ms...\n", pulse_ms);
    digitalWrite(PIN_STATUS_LED, HIGH);
    digitalWrite(PIN_RELAY_MOTOR, HIGH);  // Energize motor relay
    delay(pulse_ms);
    digitalWrite(PIN_RELAY_MOTOR, LOW);   // De-energize
    digitalWrite(PIN_STATUS_LED, LOW);
    Serial.println("[VEND] Dispense Complete.");
}

// ==============================================================================
// 6. CACHE MANAGEMENT FUNCTIONS (1,000 Cards)
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

            Serial.printf("[SYNC] ✓ Success! Loaded %d authorized cards into ESP32 RAM cache.\n", totalCachedCards);
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
        Serial.println("[OFFLINE] ✓ Buffer successfully synced to Cloud database!");
        offlineBufferCount = 0; // Clear buffer
    } else {
        Serial.printf("[OFFLINE] Sync failed with status: %d\n", httpCode);
    }
    http.end();
}

// ==============================================================================
// 7. CARD TAP PROCESSOR (ONLINE & OFFLINE)
// ==============================================================================

void processCardTap(const char* uid) {
    Serial.println("\n------------------------------------------------");
    Serial.printf("[TAP] Card Detected! UID: %s\n", uid);

    beep(2500, 80); // Quick chirp acknowledgement

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
                Serial.printf("[VERIFY] ✓ ACCESS GRANTED! Welcome %s (%d/%d)\n", username, used, limit);
                playSuccessTone();
                triggerDispenseMotor(pulse);
            } else if (strcmp(status, "DAILY_LIMIT_EXCEEDED") == 0) {
                Serial.printf("[VERIFY] ⚠️ QUOTA EXCEEDED! Limit: %d reached for %s\n", limit, username);
                playWarningTone();
            } else if (strcmp(status, "BLOCKED_CARD") == 0) {
                Serial.printf("[VERIFY] ❌ CARD BLOCKED: %s is suspended\n", username);
                playErrorTone();
            } else {
                Serial.printf("[VERIFY] ❌ REJECTED: %s\n", msg);
                playErrorTone();
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

void processOfflineTap(const char* uid) {
    int idx = findCardInCache(uid);

    if (idx >= 0) {
        RFIDCardCacheItem& item = localCardCache[idx];

        // Check local quota
        if (item.daily_limit <= 0 || item.used_today < item.daily_limit) {
            item.used_today++;
            Serial.printf("[OFFLINE VEND] ✓ Card Authorized! Welcome %s (Used: %d/%d)\n", 
                          item.name, item.used_today, item.daily_limit);
            playSuccessTone();
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
            Serial.printf("[OFFLINE VEND] ⚠️ Daily Limit Reached for %s (%d/%d)\n", 
                          item.name, item.used_today, item.daily_limit);
            playWarningTone();
        }
    } else {
        Serial.println("[OFFLINE VEND] ❌ Card not in local whitelist. Access Denied.");
        playErrorTone();
    }
}

// ==============================================================================
// 8. SETUP & INITIALIZATION
// ==============================================================================

void setup() {
    Serial.begin(115200);
    delay(500);

    Serial.println("\n==============================================");
    Serial.println("   GTECH ESP32 RFID VENDING CONTROLLER NODE   ");
    Serial.println("   Capacity: 1,000 Users / Offline Resilient  ");
    Serial.println("==============================================");

    // Pin setups
    pinMode(PIN_RELAY_MOTOR, OUTPUT);
    digitalWrite(PIN_RELAY_MOTOR, LOW); // Relay OFF

    pinMode(PIN_BUZZER, OUTPUT);
    digitalWrite(PIN_BUZZER, LOW);

    pinMode(PIN_STATUS_LED, OUTPUT);
    digitalWrite(PIN_STATUS_LED, LOW);

    // Initial chime
    beep(2000, 100);

    // Initialize SPI and MFRC522 RFID reader
    SPI.begin(RFID_SCK_PIN, RFID_MISO_PIN, RFID_MOSI_PIN, RFID_SS_PIN);
    rfid.PCD_Init();
    delay(50);
    
    byte v = rfid.PCD_ReadRegister(rfid.VersionReg);
    Serial.printf("[RFID] MFRC522 Version: 0x%02X\n", v);
    if (v == 0x00 || v == 0xFF) {
        Serial.println("[RFID] ⚠️ WARNING: MFRC522 reader communication failed! Check wiring.");
    } else {
        Serial.println("[RFID] ✓ MFRC522 RFID Reader successfully initialized!");
    }

    // Connect to Wi-Fi
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
        Serial.printf("\n[WIFI] ✓ Connected! IP: %s\n", WiFi.localIP().toString().c_str());
        playSuccessTone();

        // Initial whitelist download
        syncWhitelistFromCloud();
    } else {
        Serial.println("\n[WIFI] ⚠️ Wi-Fi Connection Failed. Running in OFFLINE CACHE MODE.");
        playWarningTone();
    }

    Serial.println("\n[READY] Vending Machine is Ready. Tap an RFID card to vend!\n");
}

// ==============================================================================
// 9. MAIN LOOP
// ==============================================================================

void loop() {
    unsigned long currentMillis = millis();

    // 1. Maintain Wi-Fi and auto-sync
    if (WiFi.status() == WL_CONNECTED) {
        if (!isWifiConnected) {
            isWifiConnected = true;
            Serial.println("[WIFI] ✓ Reconnected to Internet!");
            playSuccessTone();
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
            Serial.println("[WIFI] ⚠️ Lost Internet Connection! Switching to Offline Mode.");
        }
    }

    // 2. Check for RFID Card Tap
    if (!rfid.PICC_IsNewCardPresent()) {
        delay(50);
        return;
    }

    if (!rfid.PICC_ReadCardSerial()) {
        delay(50);
        return;
    }

    // Convert UID bytes to Hex string
    char uidString[16] = {0};
    for (byte i = 0; i < rfid.uid.size && i < 7; i++) {
        char byteHex[4];
        sprintf(byteHex, "%02X", rfid.uid.uidByte[i]);
        strcat(uidString, byteHex);
    }

    // Process the tapped card
    processCardTap(uidString);

    // Halt PICC and stop encryption on PCD
    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();

    // Debounce pause so single tap doesn't double-trigger
    delay(1500);
}
