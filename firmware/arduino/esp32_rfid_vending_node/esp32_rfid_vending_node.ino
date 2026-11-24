/*
 * ==============================================================================
 * GTECH SMART IOT FLEET PLATFORM
 * Node Type: ESP32 RFID Card-Based Vending Machine Controller
 * File: esp32_rfid_vending_node.ino
 * Firmware: v2.5.0-rfid-zero-touch
 * ==============================================================================
 * Features:
 *   - Zero-Touch Auto-Registration: Dynamic MAC-based Cloud Discovery (Like QR Machine!)
 *   - Automatic Discovery Queue with On-Screen Silicon MAC & IP Pairing Screen
 *   - Instant Claim Activation: Adopts Machine ID from Cloud within 3 seconds
 *   - 3.5" / 4.0" ILI9488 320x480 SPI TFT LCD Display (Vertical Portrait)
 *   - Matches the exact UI design and theme of the QR Vending Machine
 *   - MFRC522 SPI 13.56MHz RFID Reader driver (Shared SPI VSPI bus)
 *   - Supports up to 1,000 users/cards in local ESP32 RAM cache
 *   - Flash NVS Persistence (<Preferences.h>): Wi-Fi, Device ID, Server URL
 *   - Cloud Remote Configuration: Update Wi-Fi and Machine ID from Web Portal
 *   - USB Serial Console for on-site bench configuration (id:, wifi:, sync, status, wipe)
 *   - Cloud Tap Verification & Dispense Authorization via REST API
 *   - Offline Resilient Vending: Dispenses even when Wi-Fi is lost
 *   - Offline Log Buffering: Syncs vends to cloud when Internet reconnects
 *   - Heartbeat Telemetry: Keeps machine status permanently ONLINE in Portal
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
 *   ILI9488 TFT LCD (320x480 SPI) - 100% IDENTICAL TO QR MACHINE:
 *     GPIO 5   ->  CS (TFT Chip Select - Same as QR Machine!)
 *     GPIO 2   ->  DC / RS (Data / Command - Same as QR Machine!)
 *     GPIO 4   ->  RESET (TFT Reset - Same as QR Machine!)
 *     GPIO 18  ->  SCK (Hardware SPI Clock - Shared with RFID)
 *     GPIO 23  ->  SDI / MOSI (Hardware SPI MOSI - Shared with RFID)
 *     NC       ->  SDO / MISO (LEAVE DISCONNECTED!)
 *     3.3V     ->  VCC & LED / BL (Do NOT connect to 5V!)
 *     GND      ->  GND
 *
 *   MFRC522 RFID READER:
 *     GPIO 15  ->  SDA / SS (Dedicated RFID Chip Select)
 *     GPIO 22  ->  RST (RFID Reset)
 *     GPIO 18  ->  SCK (Hardware SPI Clock - Shared with TFT)
 *     GPIO 23  ->  MOSI (Hardware SPI MOSI - Shared with TFT)
 *     GPIO 19  ->  MISO (Hardware SPI MISO - Dedicated to RFID!)
 *     3.3V     ->  3.3V (Do NOT connect to 5V!)
 *     GND      ->  GND
 *
 *   ACTUATORS & INDICATORS:
 *     GPIO 26  ->  Motor Dispense Relay (Active HIGH)
 *     GPIO 27  ->  Piezo Buzzer (Active HIGH)
 * ==============================================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <MFRC522.h>
#include <ArduinoJson.h>
#include <DIYables_TFT_SPI.h>
#include <Preferences.h>
#include <esp_mac.h>

// ------------------------------------------------------------------------------
// HARDWARE MAC & SILICON CHIP ID UTILITY (ZERO-TOUCH)
// ------------------------------------------------------------------------------
String getDeviceMacAddress() {
    WiFi.mode(WIFI_STA);
    String mac = WiFi.macAddress();
    if (mac.length() == 17 && mac != "00:00:00:00:00:00") {
        mac.toUpperCase();
        return mac;
    }
    uint64_t chipmac = ESP.getEfuseMac();
    uint8_t* m = (uint8_t*)&chipmac;
    char macStr[18];
    snprintf(macStr, sizeof(macStr), "%02X:%02X:%02X:%02X:%02X:%02X",
             m[0], m[1], m[2], m[3], m[4], m[5]);
    return String(macStr);
}

// ==============================================================================
// 1. HARDWARE PIN DEFINITIONS
// ==============================================================================

// Shared Hardware SPI Pins (VSPI on ESP32)
#define SPI_SCK_PIN        18    // Hardware SPI Clock
#define SPI_MISO_PIN       19    // Hardware SPI MISO (RFID)
#define SPI_MOSI_PIN       23    // Hardware SPI MOSI (RFID & TFT)

// ILI9488 320x480 TFT LCD Dedicated Pins (100% IDENTICAL TO QR MACHINE)
#define TFT_CS_PIN         5     // TFT Chip Select (Exact same as QR Machine)
#define TFT_DC_PIN         2     // TFT Data / Command (Exact same as QR Machine)
#define TFT_RST_PIN        4     // TFT Reset Pin (Exact same as QR Machine)
#define TFT_WIDTH          320
#define TFT_HEIGHT         480
#define TFT_ROTATION       0     // 0 = Vertical Portrait (320w x 480h)

// MFRC522 RFID Dedicated Pins
#define RFID_SS_PIN        15    // RFID Chip Select / SDA (Assigned to GPIO 15)
#define RFID_RST_PIN       22    // RFID Reset Pin (GPIO 22)

// Actuators & Indicators
#define PIN_RELAY_MOTOR    26    // Dispense Motor Relay (Active HIGH)
#define PIN_BUZZER         27    // Buzzer (Active HIGH)

// ==============================================================================
// 2. NETWORK, STORAGE & CLOUD SERVER CONFIGURATION
// ==============================================================================

Preferences prefs;

// Default compiled Wi-Fi credentials (100% matches QR code machine defaults)
String wifi_ssid       = "IOTHUB";
String wifi_pass       = "IOTHUB07";

// Production Cloud Server Base URL
String server_base_url = "http://www.gtechinfo.in";

// Machine Identifier: Defaults to AUTO for Zero-Touch Dynamic MAC registration
String device_id       = "AUTO";
String device_token    = "dev_token_generic";

int current_config_version = 1;

// Cloud-Controlled Card Acceptance Security Policy
String card_policy     = "VENDOR_ONLY"; // "VENDOR_ONLY" (only GTECH cards) or "ALLOW_ALL" (open whitelist)
String vendor_prefix   = "GTECH";       // Expected watermark prefix in Sector 1 Block 4
String pendingSerialWrite = "";         // Holds manual watermark command from Serial Monitor

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

// Offline Log Buffer (Holds up to 500 offline vends with FIFO circular retention)
#define MAX_OFFLINE_BUFFER 500
struct OfflineVendRecord {
    char uid[12];
    uint32_t timestamp_sec;
    int dispense_ms;
};
OfflineVendRecord offlineBuffer[MAX_OFFLINE_BUFFER];
int offlineBufferCount = 0;

// State flags and timing
bool isWifiConnected = false;
unsigned long lastHeartbeatTime = 0;
unsigned long lastCardSyncTime = 0;
const unsigned long SYNC_INTERVAL_MS = 300000;      // Whitelist sync every 5 minutes
const unsigned long HEARTBEAT_INTERVAL_MS = 60000;  // Normal poll every 60 seconds
const unsigned long DISCOVERY_POLL_MS = 3000;       // Fast 3-second poll during Discovery mode

// Hardware Driver Objects
DIYables_ILI9488_SPI tft(TFT_WIDTH, TFT_HEIGHT, TFT_CS_PIN, TFT_DC_PIN, TFT_RST_PIN);
MFRC522 rfid(RFID_SS_PIN, RFID_RST_PIN);

// Forward Declarations
void printHelpMenu();
void handleSerialCommand(String cmd);
void syncWhitelistFromCloud();
void checkForRemoteConfigUpdates();
bool authenticateWithCloud();
void uiDrawStandbyScreen();
void uiDrawPendingDiscoveryScreen();
bool writeSerialToCardSector(const char* serialText);
bool readSerialFromCardSector(char* outBuffer, byte bufferSize);
void processCardTap(const char* uid, bool isVendorCard, const char* sectorData);
void processOfflineTap(const char* uid, bool isVendorCard);
void uiDrawCardEnrolledScreen(const char* name, const char* empId, const char* uid, const char* nextName, const char* nextEmpId, int qIndex, int qTotal);
void uiDrawLiveCapturedScreen(const char* uid);
void saveLocalCacheToNVS();
void loadLocalCacheFromNVS();
void saveOfflineBufferToNVS();
void loadOfflineBufferFromNVS();
void clearOfflineBufferInNVS();


// ==============================================================================
// 5. FLASH NVS PERSISTENCE HANDLERS (Preferences)
// ==============================================================================

void loadPersistentConfig() {
    prefs.begin("vending_cfg", false);
    String saved_ssid     = prefs.getString("ssid", "");
    String saved_pass     = prefs.getString("pass", "");
    String saved_url      = prefs.getString("srv_url", "");
    String last_code_ssid = prefs.getString("code_ssid", "");
    bool has_remote_wifi  = prefs.getBool("wifi_remote", false);
    String saved_dev_id   = prefs.getString("dev_id", "");
    current_config_version = prefs.getInt("cfg_ver", 1);
    card_policy            = prefs.getString("card_pol", "VENDOR_ONLY");
    vendor_prefix          = prefs.getString("ven_pfx", "GTECH");

    // --- SMART WI-FI SELECTION (Same as QR Machine) ---
    if (has_remote_wifi && saved_ssid.length() > 0) {
        wifi_ssid = saved_ssid;
        wifi_pass = saved_pass;
        Serial.printf("[Config] 📶 Cloud/Saved Wi-Fi active: %s\n", wifi_ssid.c_str());
    } else if (wifi_ssid.length() > 0 && wifi_ssid != last_code_ssid) {
        prefs.putString("ssid", wifi_ssid);
        prefs.putString("pass", wifi_pass);
        prefs.putString("code_ssid", wifi_ssid);
        Serial.printf("[Config] ⭐ New Wi-Fi from sketch code detected & applied: %s\n", wifi_ssid.c_str());
    } else if (saved_ssid.length() > 0) {
        wifi_ssid = saved_ssid;
        wifi_pass = saved_pass;
    }

    if (saved_url.length() > 0) {
        server_base_url = saved_url;
    }

    // --- DYNAMIC FLEET IDENTITY RESOLUTION (ZERO-TOUCH) ---
    if (saved_dev_id.length() > 0 && saved_dev_id != "AUTO" && saved_dev_id != "PENDING") {
        device_id = saved_dev_id;
        device_token = prefs.getString("token", "dev_token_" + device_id);
        Serial.printf("[Config] 💾 Machine ID loaded from Flash NVS: %s\n", device_id.c_str());
    } else {
        device_id = "AUTO";
        device_token = "dev_token_generic";
        Serial.printf("[Config] 🌐 Zero-Touch Mode: Machine ID will be assigned by Cloud Gateway from MAC: %s\n", 
                      getDeviceMacAddress().c_str());
    }
    prefs.end();

    Serial.println("\n==================================================================");
    Serial.println("  >>> ⚡ GTECH ESP32 RFID ZERO-TOUCH VENDING CONTROLLER <<<      ");
    Serial.println("==================================================================");
    Serial.printf("  Device ID (Machine)  : %s\n", device_id.c_str());
    Serial.printf("  Hardware MAC Address : %s\n", getDeviceMacAddress().c_str());
    Serial.printf("  Target Wi-Fi SSID    : %s\n", wifi_ssid.c_str());
    Serial.printf("  Cloud Server Base URL: %s\n", server_base_url.c_str());
    Serial.printf("  Card Security Policy : %s\n", card_policy.c_str());
    Serial.printf("  Vendor Sector Prefix : %s\n", vendor_prefix.c_str());
    Serial.printf("  Local Cache Capacity : %d Cards\n", MAX_CACHED_CARDS);
    Serial.println("==================================================================\n");
}

void savePersistentConfig(String ssid, String pass, String dev_id, String srv_url) {
    prefs.begin("vending_cfg", false);
    prefs.putString("ssid", ssid);
    prefs.putString("pass", pass);
    prefs.putBool("wifi_remote", true);
    prefs.putString("dev_id", dev_id);
    prefs.putString("token", "dev_token_" + dev_id);
    prefs.putString("srv_url", srv_url);
    prefs.putString("code_ssid", ssid);
    prefs.end();

    wifi_ssid = ssid;
    wifi_pass = pass;
    device_id = dev_id;
    server_base_url = srv_url;
    Serial.println("[✓] Settings saved to Flash NVS.");
}

void clearPersistentConfig() {
    prefs.begin("vending_cfg", false);
    prefs.clear();
    prefs.end();
    prefs.begin("rfid_cache", false);
    prefs.clear();
    prefs.end();
    prefs.begin("rfid_offline", false);
    prefs.clear();
    prefs.end();
    Serial.println("[!] Flash NVS wiped clean (Config, Card Cache & Offline Buffer).");
}

// ------------------------------------------------------------------------------
// PERSISTENT CARD WHITELIST CACHE (Flash NVS across power cycles)
// ------------------------------------------------------------------------------

void saveLocalCacheToNVS() {
    prefs.begin("rfid_cache", false);
    prefs.putInt("count", totalCachedCards);
    int chunkIdx = 0;
    for (int i = 0; i < totalCachedCards; i += 50) {
        int chunkSize = ((totalCachedCards - i) < 50) ? (totalCachedCards - i) : 50;
        String key = "c" + String(chunkIdx);
        prefs.putBytes(key.c_str(), &localCardCache[i], chunkSize * sizeof(RFIDCardCacheItem));
        chunkIdx++;
    }
    // Clean up any old unused chunks
    for (int j = chunkIdx; j < 20; j++) {
        String key = "c" + String(j);
        prefs.remove(key.c_str());
    }
    prefs.end();
    Serial.printf("[NVS CACHE] 💾 Saved %d authorized cards to Flash NVS memory.\n", totalCachedCards);
}

void loadLocalCacheFromNVS() {
    prefs.begin("rfid_cache", true); // Read-only mode
    int savedCount = prefs.getInt("count", 0);
    if (savedCount > 0 && savedCount <= MAX_CACHED_CARDS) {
        totalCachedCards = savedCount;
        int chunkIdx = 0;
        for (int i = 0; i < totalCachedCards; i += 50) {
            int chunkSize = ((totalCachedCards - i) < 50) ? (totalCachedCards - i) : 50;
            String key = "c" + String(chunkIdx);
            prefs.getBytes(key.c_str(), &localCardCache[i], chunkSize * sizeof(RFIDCardCacheItem));
            chunkIdx++;
        }
        Serial.printf("[NVS CACHE] 📂 Loaded %d authorized cards from Flash memory (Ready for Offline Operation)!\n", totalCachedCards);
    } else {
        totalCachedCards = 0;
        Serial.println("[NVS CACHE] No cards stored in Flash NVS yet. Waiting for first cloud sync.");
    }
    prefs.end();
}

// ------------------------------------------------------------------------------
// PERSISTENT OFFLINE VEND EVENT BUFFER (Flash NVS across power cycles)
// ------------------------------------------------------------------------------

void saveOfflineBufferToNVS() {
    prefs.begin("rfid_offline", false);
    prefs.putInt("cnt", offlineBufferCount);
    int chunkIdx = 0;
    for (int i = 0; i < offlineBufferCount; i += 50) {
        int chunkSize = ((offlineBufferCount - i) < 50) ? (offlineBufferCount - i) : 50;
        String key = "b" + String(chunkIdx);
        prefs.putBytes(key.c_str(), &offlineBuffer[i], chunkSize * sizeof(OfflineVendRecord));
        chunkIdx++;
    }
    // Clean up any old unused chunks
    for (int j = chunkIdx; j < 10; j++) {
        String key = "b" + String(j);
        prefs.remove(key.c_str());
    }
    prefs.remove("buf"); // Clean legacy key
    prefs.end();
    Serial.printf("[OFFLINE NVS] 💾 Saved %d pending offline vends to Flash memory (%d chunks).\n", offlineBufferCount, chunkIdx);
}

void loadOfflineBufferFromNVS() {
    prefs.begin("rfid_offline", false);
    int savedCount = prefs.getInt("cnt", 0);
    if (savedCount > 0 && savedCount <= MAX_OFFLINE_BUFFER) {
        offlineBufferCount = savedCount;
        int chunkIdx = 0;
        for (int i = 0; i < offlineBufferCount; i += 50) {
            int chunkSize = ((offlineBufferCount - i) < 50) ? (offlineBufferCount - i) : 50;
            String key = "b" + String(chunkIdx);
            prefs.getBytes(key.c_str(), &offlineBuffer[i], chunkSize * sizeof(OfflineVendRecord));
            chunkIdx++;
        }
        Serial.printf("[OFFLINE NVS] 📂 Restored %d pending offline vends from Flash memory (Ready to Upload)!\n", offlineBufferCount);
    } else {
        offlineBufferCount = 0;
    }
    prefs.end();
}

void clearOfflineBufferInNVS() {
    prefs.begin("rfid_offline", false);
    prefs.putInt("cnt", 0);
    for (int j = 0; j < 10; j++) {
        String key = "b" + String(j);
        prefs.remove(key.c_str());
    }
    prefs.remove("buf");
    prefs.end();
    Serial.println("[OFFLINE NVS] 🗑️ Cleared offline vend buffer in Flash memory.");
}

// ==============================================================================
// 6. SPI BUS ARBITRATION HELPERS
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
// 7. BUZZER AUDIO FEEDBACK HELPER
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
// 8. TFT LCD UI DRAWING FUNCTIONS
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
    tft.print("Hardware MAC  : ");
    tft.setTextColor(COLOR_CYAN);
    tft.println(getDeviceMacAddress());

    tft.setCursor(30, 245);
    tft.setTextColor(COLOR_WHITE);
    tft.print("Machine ID    : ");
    tft.setTextColor(COLOR_GREEN);
    tft.println(device_id);

    tft.setCursor(30, 270);
    tft.setTextColor(COLOR_WHITE);
    tft.print("Firmware      : v2.5.0-rfid-zero-touch");

    tft.setCursor(30, 295);
    tft.print("Capacity      : 1,000 Cards Cache");

    tft.setCursor(30, 320);
    tft.print("Display       : ILI9488 320x480 SPI");

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

/**
 * Screen: Hardware Discovery & Zero-Touch Web Pairing Screen (Matches QR Machine)
 * Shown when an unassigned ESP32 connects and waits for admin claim in Web Portal.
 */
void uiDrawPendingDiscoveryScreen() {
    selectTFT();
    tft.fillScreen(COLOR_BG);

    // Top Blue Header
    tft.fillRect(0, 0, TFT_WIDTH, 50, COLOR_BLUE);
    tft.setCursor(15, 14);
    tft.setTextColor(COLOR_WHITE);
    tft.setTextSize(2);
    tft.print("G-TECH SMART FLEET");

    // Center Card
    tft.fillRect(15, 65, 290, 395, COLOR_CARD);
    tft.drawRect(15, 65, 290, 395, COLOR_BLUE);

    // Discovery Badge
    tft.fillRect(25, 80, 270, 35, COLOR_BG);
    tft.drawRect(25, 80, 270, 35, COLOR_CYAN);
    tft.setCursor(32, 90);
    tft.setTextColor(COLOR_CYAN);
    tft.setTextSize(2);
    tft.print("NEW RFID DETECTED");

    // Hardware Details
    tft.setCursor(25, 135);
    tft.setTextColor(COLOR_MUTED);
    tft.setTextSize(1);
    tft.print("SILICON MAC ADDRESS:");

    tft.setCursor(25, 155);
    tft.setTextColor(COLOR_YELLOW);
    tft.setTextSize(2);
    tft.print(getDeviceMacAddress().c_str());

    tft.setCursor(25, 195);
    tft.setTextColor(COLOR_MUTED);
    tft.setTextSize(1);
    tft.print("ASSIGNED IP ADDRESS:");

    tft.setCursor(25, 215);
    tft.setTextColor(COLOR_GREEN);
    tft.setTextSize(2);
    tft.print(WiFi.localIP().toString().c_str());

    // Call to action
    tft.fillRect(25, 260, 270, 105, COLOR_BG);
    tft.drawRect(25, 260, 270, 105, COLOR_CARD_BORDER);

    tft.setCursor(35, 275);
    tft.setTextColor(COLOR_WHITE);
    tft.setTextSize(2);
    tft.print("READY TO PAIR");

    tft.setCursor(35, 305);
    tft.setTextColor(COLOR_CYAN);
    tft.setTextSize(1);
    tft.print("Open Web Portal to claim or assign");
    tft.setCursor(35, 322);
    tft.print("Machine ID in Discovery Queue.");

    tft.setCursor(35, 345);
    tft.setTextColor(COLOR_MUTED);
    tft.print("Auto-checking every 3 sec...");

    // Serial monitor prompt
    tft.fillRect(25, 375, 270, 70, COLOR_BG);
    tft.drawRect(25, 375, 270, 70, COLOR_CARD_BORDER);
    tft.setCursor(35, 388);
    tft.setTextColor(COLOR_YELLOW);
    tft.setTextSize(1);
    tft.print("Or Enter in Serial Monitor:");
    tft.setCursor(35, 410);
    tft.setTextColor(COLOR_GREEN);
    tft.setTextSize(2);
    tft.print("id:RFID-000001");

    deselectTFT();

    Serial.println("\n==================================================================");
    Serial.println(">>> [DISCOVERY MODE] WAITING FOR MACHINE ID ASSIGNMENT <<<");
    Serial.printf("  Hardware MAC : %s\n", getDeviceMacAddress().c_str());
    Serial.printf("  Assigned IP  : %s\n", WiFi.localIP().toString().c_str());
    Serial.println("  OPTION 1: Assign in Web Portal (http://www.gtechinfo.in)");
    Serial.println("  OPTION 2: Type 'id:RFID-000001' in Serial Monitor now!");
    Serial.println("==================================================================\n");
}

void uiDrawWiFiUpdatingScreen(const String& newSsid) {
    selectTFT();
    tft.fillScreen(COLOR_BG);

    tft.fillRect(0, 0, TFT_WIDTH, 55, COLOR_HEADER);
    tft.drawFastHLine(0, 55, TFT_WIDTH, COLOR_CYAN);

    tft.setCursor(20, 18);
    tft.setTextColor(COLOR_CYAN);
    tft.setTextSize(2);
    tft.print("CLOUD WI-FI UPDATE");

    tft.fillRoundRect(16, 80, 288, 330, 12, COLOR_CARD);
    tft.drawRoundRect(16, 80, 288, 330, 12, COLOR_CYAN);

    tft.setCursor(30, 105);
    tft.setTextColor(COLOR_YELLOW);
    tft.setTextSize(2);
    tft.print("NEW CONFIG RECEIVED");

    tft.setCursor(30, 150);
    tft.setTextColor(COLOR_WHITE);
    tft.setTextSize(1);
    tft.print("Credentials updated remotely from");
    tft.setCursor(30, 170);
    tft.print("G-TECH Cloud Management Portal.");

    tft.setCursor(30, 215);
    tft.setTextColor(COLOR_MUTED);
    tft.print("New Network SSID:");

    tft.setCursor(30, 240);
    tft.setTextColor(COLOR_GREEN);
    tft.setTextSize(2);
    tft.print(newSsid);

    tft.setCursor(30, 295);
    tft.setTextColor(COLOR_WHITE);
    tft.setTextSize(1);
    tft.print("Saving credentials to Flash NVS...");
    tft.setCursor(30, 320);
    tft.setTextColor(COLOR_CYAN);
    tft.print("Reconnecting to new network...");

    deselectTFT();
}

void uiDrawStandbyScreen() {
    if (device_id == "AUTO" || device_id == "PENDING" || device_id.length() == 0) {
        uiDrawPendingDiscoveryScreen();
        return;
    }

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

    // Machine ID Sub-bar (Dynamic Device ID)
    tft.fillRect(0, 56, TFT_WIDTH, 28, COLOR_CARD);
    tft.setCursor(20, 64);
    tft.setTextColor(COLOR_MUTED);
    tft.setTextSize(1);
    tft.printf("NODE: %s  |  MODE: %s", device_id.c_str(), card_policy == "VENDOR_ONLY" ? "VENDOR ONLY" : "OPEN FLEET");

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

    tft.fillRoundRect(16, 100, 288, 280, 12, COLOR_CARD);
    tft.drawRoundRect(16, 100, 288, 280, 12, COLOR_GREEN);

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

    tft.setCursor(30, 255);
    tft.setTextColor(COLOR_MUTED);
    tft.setTextSize(1);
    if (limit <= 0) {
        tft.print("Today's Allowance: Unlimited");
    } else {
        tft.printf("Today's Allowance: %d of %d Used", used, limit);
    }

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

    tft.fillRoundRect(16, 100, 288, 280, 12, COLOR_CARD);
    tft.drawRoundRect(16, 100, 288, 280, 12, COLOR_RED);

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
// 8B. MIFARE CLASSIC SECTOR DATA WRITER & ENROLLMENT UI
// ==============================================================================

bool readSerialFromCardSector(char* outBuffer, byte bufferSize) {
    if (!outBuffer || bufferSize < 17) return false;
    memset(outBuffer, 0, bufferSize);

    MFRC522::MIFARE_Key key;
    for (byte i = 0; i < 6; i++) key.keyByte[i] = 0xFF; // Factory default Key A

    byte blockAddr = 4; // Sector 1 Block 0 (Block 4: Standard user data block)
    byte buffer[18];
    byte byteCount = sizeof(buffer);

    selectRFID();
    rfid.PCD_StopCrypto1(); // Reset any residual crypto state

    MFRC522::StatusCode status = (MFRC522::StatusCode) rfid.PCD_Authenticate(
        MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockAddr, &key, &(rfid.uid)
    );

    if (status != MFRC522::STATUS_OK) {
        rfid.PCD_StopCrypto1();
        deselectRFID();
        return false;
    }

    status = (MFRC522::StatusCode) rfid.MIFARE_Read(blockAddr, buffer, &byteCount);
    rfid.PCD_StopCrypto1(); // Always stop crypto after reading
    deselectRFID();

    if (status != MFRC522::STATUS_OK) {
        return false;
    }

    char temp[17];
    memcpy(temp, buffer, 16);
    temp[16] = '\0';

    int len = 16;
    while (len > 0 && (temp[len - 1] == ' ' || (unsigned char)temp[len - 1] < 32 || (unsigned char)temp[len - 1] > 126)) {
        temp[len - 1] = '\0';
        len--;
    }

    strncpy(outBuffer, temp, bufferSize - 1);
    outBuffer[bufferSize - 1] = '\0';
    return true;
}

bool writeSerialToCardSector(const char* serialText) {
    if (!serialText || strlen(serialText) == 0) return false;

    MFRC522::MIFARE_Key key;
    for (byte i = 0; i < 6; i++) key.keyByte[i] = 0xFF; // Factory default Key A

    byte blockAddr = 4; // Sector 1 Block 0 (Block 4: Standard user data block)
    byte buffer[16];
    memset(buffer, ' ', 16); // Pad 16-byte block with spaces
    int len = strlen(serialText);
    if (len > 16) len = 16;
    memcpy(buffer, serialText, len);

    selectRFID();

    // Retry up to 3 attempts with fresh card re-selection (handles delay after Wi-Fi HTTP roundtrip)
    bool writeSuccess = false;
    for (int attempt = 1; attempt <= 3; attempt++) {
        rfid.PCD_StopCrypto1();

        // Re-wake & re-select the PICC in case communication was idle during Wi-Fi HTTP roundtrip
        byte bufferATQA[2];
        byte bufferSize = sizeof(bufferATQA);
        rfid.PICC_WakeupA(bufferATQA, &bufferSize);
        rfid.PICC_Select(&(rfid.uid));

        MFRC522::StatusCode status = (MFRC522::StatusCode) rfid.PCD_Authenticate(
            MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockAddr, &key, &(rfid.uid)
        );

        if (status == MFRC522::STATUS_OK) {
            status = (MFRC522::StatusCode) rfid.MIFARE_Write(blockAddr, buffer, 16);
            if (status == MFRC522::STATUS_OK) {
                Serial.printf("[RFID WRITE] ✓ SUCCESS! Permanently wrote '%s' into Sector 1 Block 4\n", serialText);
                writeSuccess = true;
                rfid.PCD_StopCrypto1();
                break;
            } else {
                Serial.printf("[RFID WRITE] ! MIFARE_Write failed on attempt %d: %s\n", attempt, rfid.GetStatusCodeName(status));
            }
        } else {
            Serial.printf("[RFID WRITE] ! Auth Key A for block %d attempt %d: %s\n", blockAddr, attempt, rfid.GetStatusCodeName(status));
        }

        rfid.PCD_StopCrypto1();
        delay(30);
    }

    deselectRFID();
    return writeSuccess;
}

void uiDrawCardEnrolledScreen(const char* name, const char* empId, const char* uid, const char* nextName, const char* nextEmpId, int qIndex, int qTotal) {
    selectTFT();

    // Main Card Panel
    tft.fillRoundRect(16, 80, 288, 380, 12, COLOR_CARD);
    tft.drawRoundRect(16, 80, 288, 380, 12, COLOR_GREEN);

    // Green Header Banner
    tft.fillRoundRect(30, 95, 260, 42, 6, COLOR_GREEN);
    tft.setCursor(45, 107);
    tft.setTextColor(COLOR_BLACK);
    tft.setTextSize(2);
    tft.print("CARD PROGRAMMED!");

    // Sequence / Queue Badge
    tft.setCursor(30, 152);
    tft.setTextColor(COLOR_CYAN);
    tft.setTextSize(2);
    tft.printf("CARD #%d OF %d", qIndex, qTotal);

    // Enrolled Cardholder Name
    tft.setCursor(30, 185);
    tft.setTextColor(COLOR_WHITE);
    tft.setTextSize(2);
    tft.print(name);

    // Employee ID / Written Serial Pattern
    tft.setCursor(30, 215);
    tft.setTextColor(COLOR_YELLOW);
    tft.setTextSize(2);
    tft.printf("ID: %s", empId);

    // Hardware Card UID
    tft.setCursor(30, 245);
    tft.setTextColor(COLOR_MUTED);
    tft.setTextSize(1);
    tft.printf("Physical UID: %s", uid);

    // Divider Line
    tft.drawFastHLine(30, 265, 260, COLOR_CARD_BORDER);

    // Next Card Box or Completion Box
    if (nextName && nextName[0] != '\0') {
        tft.fillRoundRect(30, 280, 260, 100, 6, COLOR_BG);
        tft.drawRoundRect(30, 280, 260, 100, 6, COLOR_CYAN);

        tft.setCursor(40, 292);
        tft.setTextColor(COLOR_CYAN);
        tft.setTextSize(1);
        tft.print(">>> NEXT IN QUEUE <<<");

        tft.setCursor(40, 310);
        tft.setTextColor(COLOR_WHITE);
        tft.setTextSize(2);
        tft.print(nextName);

        tft.setCursor(40, 335);
        tft.setTextColor(COLOR_YELLOW);
        tft.setTextSize(1);
        tft.printf("Target ID: %s", nextEmpId ? nextEmpId : "");

        tft.setCursor(40, 355);
        tft.setTextColor(COLOR_GREEN);
        tft.setTextSize(1);
        tft.print("TAP BLANK CARD NOW...");
    } else {
        tft.fillRoundRect(30, 285, 260, 90, 6, COLOR_GREEN);
        tft.setCursor(45, 305);
        tft.setTextColor(COLOR_BLACK);
        tft.setTextSize(2);
        tft.print("ALL CARDS DONE!");

        tft.setCursor(45, 335);
        tft.setTextColor(COLOR_BLACK);
        tft.setTextSize(1);
        tft.printf("Successfully enrolled %d cards.", qTotal);
    }

    deselectTFT();
}


// ==============================================================================
// 9. MOTOR RELAY CONTROL
// ==============================================================================


void uiDrawLiveCapturedScreen(const char* uid) {
    selectTFT();

    tft.fillRoundRect(16, 90, 288, 300, 12, COLOR_CARD);
    tft.drawRoundRect(16, 90, 288, 300, 12, COLOR_CYAN);

    tft.fillRoundRect(30, 110, 260, 45, 6, COLOR_CYAN);
    tft.setCursor(45, 123);
    tft.setTextColor(COLOR_BLACK);
    tft.setTextSize(2);
    tft.print("CARD CAPTURED!");

    tft.setCursor(30, 175);
    tft.setTextColor(COLOR_WHITE);
    tft.setTextSize(1);
    tft.print("Silicon Hardware UID:");

    tft.setCursor(30, 195);
    tft.setTextColor(COLOR_YELLOW);
    tft.setTextSize(3);
    tft.print(uid);

    tft.drawFastHLine(30, 245, 260, COLOR_CARD_BORDER);

    tft.setCursor(30, 265);
    tft.setTextColor(COLOR_GREEN);
    tft.setTextSize(2);
    tft.print("CHECK BROWSER");

    tft.setCursor(30, 295);
    tft.setTextColor(COLOR_MUTED);
    tft.setTextSize(1);
    tft.print("Forwarded to Live Enroll Portal.");

    tft.setCursor(30, 315);
    tft.print("Type staff name and click Save.");

    deselectTFT();
}

void triggerDispenseMotor(int pulse_ms) {
    Serial.printf("[VEND] Activating Relay Motor for %d ms...\n", pulse_ms);
    digitalWrite(PIN_RELAY_MOTOR, HIGH);  // Energize motor relay
    delay(pulse_ms);
    digitalWrite(PIN_RELAY_MOTOR, LOW);   // De-energize
    Serial.println("[VEND] Dispense Complete.");

    uiDrawVendCompleteScreen();
    delay(1200);
    uiDrawStandbyScreen();
}

// ==============================================================================
// 10. CLOUD HANDSHAKE & DYNAMIC IDENTITY (ZERO-TOUCH)
// ==============================================================================

bool authenticateWithCloud() {
    if (WiFi.status() != WL_CONNECTED) return false;

    WiFiClient client;
    HTTPClient http;
    String endpoint = server_base_url + "/api/v1/device-gateway/authenticate";

    String realMac = getDeviceMacAddress();
    String chipId = "ESP32-CHIP-" + String((uint32_t)ESP.getEfuseMac(), HEX);

    Serial.printf("\n[Cloud] Authenticating Machine '%s' (MAC: %s, Chip: %s) with Server: %s...\n",
                  device_id.c_str(), realMac.c_str(), chipId.c_str(), endpoint.c_str());
    http.setConnectTimeout(3000);
    http.setTimeout(3000);
    http.begin(client, endpoint);
    http.addHeader("Content-Type", "application/json");

    StaticJsonDocument<768> doc;
    doc["device_id"]        = device_id;
    doc["chip_id"]          = chipId;
    doc["mac_address"]      = realMac;
    doc["device_token"]     = device_token;
    doc["firmware_version"] = "v2.5.0-rfid-zero-touch";
    doc["boot_count"]       = 1;

    String reqBody;
    serializeJson(doc, reqBody);
    int httpCode = http.POST(reqBody);

    if (httpCode == 200) {
        String resp = http.getString();
        StaticJsonDocument<1024> respDoc;
        deserializeJson(respDoc, resp);

        if (respDoc.containsKey("device_id")) {
            String assignedId = respDoc["device_id"].as<String>();
            if (assignedId.length() > 0 && assignedId != "AUTO" && assignedId != "PENDING") {
                bool idChanged = (assignedId != device_id);
                device_id = assignedId;
                device_token = "dev_token_" + device_id;

                prefs.begin("vending_cfg", false);
                prefs.putString("dev_id", device_id);
                prefs.putString("token", device_token);
                prefs.end();

                if (idChanged) {
                    Serial.println("\n==================================================================");
                    Serial.printf(">>> [✓ DYNAMIC FLEET IDENTITY ASSIGNED] Machine ID: %s <<<\n", device_id.c_str());
                    Serial.printf("    Bound to Hardware MAC: %s\n", realMac.c_str());
                    Serial.println("    Saved to Flash NVS. Pulling authorized card whitelist...");
                    Serial.println("==================================================================\n");
                    playSuccessTone();
                    uiDrawStandbyScreen();
                    syncWhitelistFromCloud();
                }
            } else if (assignedId == "PENDING") {
                Serial.printf("[Cloud] Device MAC %s in Discovery Queue. Waiting for admin claim in Portal.\n", realMac.c_str());
                if (device_id != "PENDING") {
                    device_id = "PENDING";
                    uiDrawPendingDiscoveryScreen();
                }
            }
        }
        http.end();
        return true;
    } else {
        Serial.printf("[Cloud] Gateway authentication response code: %d\n", httpCode);
    }
    http.end();
    return false;
}

// ==============================================================================
// 11. CACHE MANAGEMENT & CLOUD SYNC (1,000 Cards)
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
    if (device_id == "AUTO" || device_id == "PENDING" || device_id.length() == 0) return;

    Serial.println("[SYNC] Requesting authorized RFID card whitelist from Cloud...");
    HTTPClient http;
    String url = server_base_url + "/api/v1/rfid-vending/devices/" + device_id + "/sync-cards";
    
    http.begin(url);
    http.setTimeout(10000);
    int httpCode = http.GET();

    if (httpCode == HTTP_CODE_OK) {
        String payload = http.getString();
        
        // Parse JSON with DynamicJsonDocument scaled for up to 1000 items
        DynamicJsonDocument doc(49152); // 48 KB json buffer
        DeserializationError err = deserializeJson(doc, payload);

        if (!err) {
            // Check for Remote Wi-Fi or Machine ID updates sent from Cloud Portal
            if (doc.containsKey("device_id")) {
                String cloudDev = doc["device_id"].as<String>();
                if (cloudDev.length() > 0 && cloudDev != "AUTO" && cloudDev != "PENDING" && cloudDev != device_id) {
                    Serial.printf("[Config] 🏷️ Machine ID updated from Cloud: %s -> %s\n", device_id.c_str(), cloudDev.c_str());
                    device_id = cloudDev;
                    device_token = "dev_token_" + device_id;
                    prefs.begin("vending_cfg", false);
                    prefs.putString("dev_id", device_id);
                    prefs.putString("token", device_token);
                    prefs.end();
                }
            }

            if (doc.containsKey("wifi_ssid")) {
                String newWifiSsid = doc["wifi_ssid"].as<String>();
                String newWifiPass = doc.containsKey("wifi_password") ? doc["wifi_password"].as<String>() : "";
                int newVer = doc.containsKey("config_version") ? doc["config_version"].as<int>() : current_config_version;

                if (newWifiSsid.length() > 0 && (newWifiSsid != wifi_ssid || newWifiPass != wifi_pass)) {
                    Serial.println("\n==================================================================");
                    Serial.println(">>> 📶 REMOTE WI-FI CREDENTIALS RECEIVED FROM CLOUD PORTAL! <<<");
                    Serial.printf("  New SSID     : %s\n", newWifiSsid.c_str());
                    Serial.printf("  New Password : %s\n", newWifiPass.length() > 0 ? "********" : "(None)");
                    Serial.println("  Saving to Flash NVS & Reconnecting to Network...");
                    Serial.println("==================================================================\n");

                    wifi_ssid = newWifiSsid;
                    wifi_pass = newWifiPass;
                    current_config_version = newVer;

                    prefs.begin("vending_cfg", false);
                    prefs.putString("ssid", wifi_ssid);
                    prefs.putString("pass", wifi_pass);
                    prefs.putBool("wifi_remote", true);
                    prefs.putString("code_ssid", wifi_ssid);
                    prefs.putInt("cfg_ver", current_config_version);
                    prefs.end();

                    uiDrawWiFiUpdatingScreen(wifi_ssid);
                    delay(2500);
                    ESP.restart();
                }
            }

            if (doc.containsKey("card_policy")) {
                String newPol = doc["card_policy"].as<String>();
                String newPfx = doc.containsKey("vendor_prefix") ? doc["vendor_prefix"].as<String>() : vendor_prefix;
                if (newPol.length() > 0 && (newPol != card_policy || newPfx != vendor_prefix)) {
                    Serial.printf("[Config] 🛡️ Card Security Policy updated from Cloud: %s (Prefix: %s)\n", newPol.c_str(), newPfx.c_str());
                    card_policy = newPol;
                    vendor_prefix = newPfx;
                    prefs.begin("vending_cfg", false);
                    prefs.putString("card_pol", card_policy);
                    prefs.putString("ven_pfx", vendor_prefix);
                    prefs.end();
                }
            }

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
            saveLocalCacheToNVS();
            uiDrawStandbyScreen();
        } else {
            Serial.printf("[SYNC] JSON parse error: %s\n", err.c_str());
        }
    } else {
        Serial.printf("[SYNC] HTTP error: %d\n", httpCode);
    }
    http.end();
}

void checkForRemoteConfigUpdates() {
    if (WiFi.status() != WL_CONNECTED) return;

    HTTPClient http;
    String queryIdentifier = (device_id == "AUTO" || device_id == "PENDING" || device_id.length() == 0) ? getDeviceMacAddress() : device_id;
    String endpoint = server_base_url + "/api/v1/orders/qr-config/" + queryIdentifier + "?mac=" + getDeviceMacAddress();
    http.setTimeout(3500);
    http.begin(endpoint);

    int httpCode = http.GET();
    if (httpCode == 200) {
        String resp = http.getString();
        StaticJsonDocument<2048> doc;
        DeserializationError err = deserializeJson(doc, resp);

        if (!err) {
            String newWifiSsid = doc.containsKey("wifi_ssid") ? doc["wifi_ssid"].as<String>() : "";
            String newWifiPass = doc.containsKey("wifi_password") ? doc["wifi_password"].as<String>() : "";
            int newVersion     = doc.containsKey("config_version") ? doc["config_version"].as<int>() : current_config_version;

            if (doc.containsKey("device_id")) {
                String cloudDev = doc["device_id"].as<String>();
                if (cloudDev.length() > 0 && cloudDev != "AUTO" && cloudDev != "PENDING" && cloudDev.indexOf(':') == -1) {
                    if (cloudDev != device_id) {
                        Serial.println("\n==================================================================");
                        Serial.printf(">>> [✓ DYNAMIC FLEET IDENTITY ASSIGNED] Machine ID: %s <<<\n", cloudDev.c_str());
                        Serial.printf("    Bound to Hardware MAC: %s\n", getDeviceMacAddress().c_str());
                        Serial.println("    Saved to Flash NVS. Initializing whitelist...");
                        Serial.println("==================================================================\n");
                        device_id = cloudDev;
                        device_token = "dev_token_" + device_id;
                        prefs.begin("vending_cfg", false);
                        prefs.putString("dev_id", device_id);
                        prefs.putString("token", device_token);
                        prefs.end();
                        playSuccessTone();
                        uiDrawStandbyScreen();
                        syncWhitelistFromCloud();
                    }
                } else if (cloudDev == "PENDING") {
                    if (device_id != "PENDING") {
                        device_id = "PENDING";
                        uiDrawPendingDiscoveryScreen();
                    }
                }
            }

            if (doc.containsKey("card_policy")) {
                String newPol = doc["card_policy"].as<String>();
                String newPfx = doc.containsKey("vendor_prefix") ? doc["vendor_prefix"].as<String>() : vendor_prefix;
                if (newPol.length() > 0 && (newPol != card_policy || newPfx != vendor_prefix)) {
                    Serial.printf("[Config] 🛡️ Card Security Policy updated from Cloud: %s (Prefix: %s)\n", newPol.c_str(), newPfx.c_str());
                    card_policy = newPol;
                    vendor_prefix = newPfx;
                    prefs.begin("vending_cfg", false);
                    prefs.putString("card_pol", card_policy);
                    prefs.putString("ven_pfx", vendor_prefix);
                    prefs.end();
                    uiDrawStandbyScreen();
                }
            }

            bool wifiChanged = (newWifiSsid.length() > 0 && (newWifiSsid != wifi_ssid || newWifiPass != wifi_pass));
            if (wifiChanged) {
                Serial.println("\n==================================================================");
                Serial.println(">>> 📶 REMOTE WI-FI CREDENTIALS RECEIVED FROM CLOUD PORTAL! <<<");
                Serial.printf("  New SSID     : %s\n", newWifiSsid.c_str());
                Serial.printf("  New Password : %s\n", newWifiPass.length() > 0 ? "********" : "(None)");
                Serial.println("  Saving to Flash NVS & Reconnecting to Network...");
                Serial.println("==================================================================\n");

                current_config_version = newVersion;
                wifi_ssid = newWifiSsid;
                wifi_pass = newWifiPass;

                prefs.begin("vending_cfg", false);
                prefs.putString("ssid", wifi_ssid);
                prefs.putString("pass", wifi_pass);
                prefs.putBool("wifi_remote", true);
                prefs.putString("code_ssid", wifi_ssid);
                prefs.putInt("cfg_ver", current_config_version);
                prefs.end();

                uiDrawWiFiUpdatingScreen(wifi_ssid);
                delay(2500);
                ESP.restart();
            }
        }
    }
    http.end();
}

void flushOfflineBufferToCloud() {
    if (offlineBufferCount == 0 || WiFi.status() != WL_CONNECTED) return;
    if (device_id == "AUTO" || device_id == "PENDING" || device_id.length() == 0) return;

    Serial.printf("[OFFLINE] Flushing %d buffered offline vends to Cloud in batches...\n", offlineBufferCount);

    while (offlineBufferCount > 0 && WiFi.status() == WL_CONNECTED) {
        int batchSize = ((offlineBufferCount < 50) ? offlineBufferCount : 50);

        HTTPClient http;
        String url = server_base_url + "/api/v1/rfid-vending/offline-sync";

        DynamicJsonDocument doc(4096);
        doc["device_id"] = device_id;
        JsonArray logs = doc.createNestedArray("logs");

        for (int i = 0; i < batchSize; i++) {
            JsonObject item = logs.createNestedObject();
            item["card_uid"] = offlineBuffer[i].uid;
            item["dispense_ms"] = offlineBuffer[i].dispense_ms;
        }

        String requestBody;
        serializeJson(doc, requestBody);

        http.begin(url);
        http.addHeader("Content-Type", "application/json");
        http.setTimeout(8000);
        int httpCode = http.POST(requestBody);

        if (httpCode == HTTP_CODE_OK || httpCode == 201) {
            Serial.printf("[OFFLINE] ✓ Batch of %d vends synced to Cloud!\n", batchSize);
            int remaining = offlineBufferCount - batchSize;
            if (remaining > 0) {
                memmove(&offlineBuffer[0], &offlineBuffer[batchSize], remaining * sizeof(OfflineVendRecord));
            }
            offlineBufferCount = remaining;
            saveOfflineBufferToNVS();
        } else {
            Serial.printf("[OFFLINE] ! Sync batch failed with HTTP code: %d. Will retry.\n", httpCode);
            http.end();
            break;
        }
        http.end();
    }

    if (offlineBufferCount == 0) {
        Serial.println("[OFFLINE] ✓ All offline buffers successfully synced to Cloud database!");
        clearOfflineBufferInNVS();
    } else {
        Serial.printf("[OFFLINE] ⚠️ %d offline vends remaining in Flash buffer for next retry.\n", offlineBufferCount);
    }
}

// ==============================================================================
// 12. CARD TAP PROCESSOR (ONLINE & OFFLINE)
// ==============================================================================

void processOfflineTap(const char* uid, bool isVendorCard) {
    if (card_policy == "VENDOR_ONLY" && !isVendorCard) {
        Serial.printf("[OFFLINE VEND] ! Card %s rejected: Outside card not permitted under VENDOR_ONLY policy.\n", uid);
        playErrorTone();
        uiDrawDeniedScreen("UNOFFICIAL CARD", "Use Official G-TECH Card");
        delay(2500);
        uiDrawStandbyScreen();
        return;
    }
    int idx = findCardInCache(uid);

    if (idx >= 0) {
        RFIDCardCacheItem& item = localCardCache[idx];

        // Check local quota
        if (item.daily_limit <= 0 || item.used_today < item.daily_limit) {
            item.used_today++;
            Serial.printf("[OFFLINE VEND] ✓ Card Authorized! Welcome %s (Used: %d/%d)\n", 
                          item.name, item.used_today, item.daily_limit);
            playSuccessTone();
            uiDrawDispenseScreen(item.name, item.used_today, item.daily_limit, DEFAULT_DISPENSE_MS);
            triggerDispenseMotor(DEFAULT_DISPENSE_MS);

            // Buffer offline vend (FIFO Circular Buffer: holds latest 500 events)
            if (offlineBufferCount < MAX_OFFLINE_BUFFER) {
                strncpy(offlineBuffer[offlineBufferCount].uid, uid, sizeof(offlineBuffer[0].uid) - 1);
                offlineBuffer[offlineBufferCount].uid[sizeof(offlineBuffer[0].uid) - 1] = '\0';
                offlineBuffer[offlineBufferCount].timestamp_sec = millis() / 1000;
                offlineBuffer[offlineBufferCount].dispense_ms = DEFAULT_DISPENSE_MS;
                offlineBufferCount++;
                Serial.printf("[OFFLINE] Buffered offline event (%d/%d queued)\n", offlineBufferCount, MAX_OFFLINE_BUFFER);
            } else {
                // Buffer is full (500 events): drop the oldest event (FIFO) and append latest event
                memmove(&offlineBuffer[0], &offlineBuffer[1], (MAX_OFFLINE_BUFFER - 1) * sizeof(OfflineVendRecord));
                int lastIdx = MAX_OFFLINE_BUFFER - 1;
                strncpy(offlineBuffer[lastIdx].uid, uid, sizeof(offlineBuffer[0].uid) - 1);
                offlineBuffer[lastIdx].uid[sizeof(offlineBuffer[0].uid) - 1] = '\0';
                offlineBuffer[lastIdx].timestamp_sec = millis() / 1000;
                offlineBuffer[lastIdx].dispense_ms = DEFAULT_DISPENSE_MS;
                Serial.printf("[OFFLINE] 🔄 Buffer full (500/500)! Oldest event dropped, keeping latest 500.\n");
            }
            saveOfflineBufferToNVS();
            saveLocalCacheToNVS();
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

void processCardTap(const char* uid, bool isVendorCard, const char* sectorData) {
    if (device_id == "AUTO" || device_id == "PENDING" || device_id.length() == 0) {
        Serial.println("[!] Machine is waiting for Device ID claim in Web Portal.");
        playWarningTone();
        uiDrawPendingDiscoveryScreen();
        return;
    }

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
        String url = server_base_url + "/api/v1/rfid-vending/verify-tap";
        http.begin(url);
        http.addHeader("Content-Type", "application/json");
        http.setTimeout(4000);

        StaticJsonDocument<384> doc;
        doc["device_id"] = device_id;
        doc["card_uid"] = uid;
        doc["pulse_ms"] = DEFAULT_DISPENSE_MS;
        doc["is_vendor_card"] = isVendorCard;
        doc["sector_data"] = sectorData;

        String requestBody;
        serializeJson(doc, requestBody);

        int httpCode = http.POST(requestBody);

        if (httpCode == HTTP_CODE_OK) {
            String responseStr = http.getString();
            StaticJsonDocument<1024> resp;
            deserializeJson(resp, responseStr);

            bool authorized = resp["authorized"] | false;
            const char* status = resp["status"] | "UNKNOWN";
            const char* username = resp["username"] | "User";
            const char* msg = resp["message"] | "";
            int pulse = resp["dispense_pulse_ms"] | DEFAULT_DISPENSE_MS;
            int used = resp["used_today"] | 0;
            int limit = resp["daily_limit"] | 1;

            // Scenario A: Sequential 100-Card Enrollment / Hardware Encoding
            if (strcmp(status, "ENROLL_SUCCESS") == 0) {
                const char* empId = resp["employee_id"] | "";
                const char* writeData = resp["write_data"] | "";
                const char* nextName = resp["next_person"] | "";
                const char* nextEmpId = resp["next_employee_id"] | "";
                int qIndex = resp["queue_index"] | 1;
                int qTotal = resp["queue_total"] | 1;

                Serial.println("\n==================================================================");
                Serial.printf(">>> [✓ SEQUENTIAL CARD PROGRAMMED] Card #%d of %d <<<\n", qIndex, qTotal);
                Serial.printf("  Person Name   : %s\n", username);
                Serial.printf("  Employee ID   : %s\n", empId);
                Serial.printf("  Hardware UID  : %s\n", uid);
                if (nextName[0]) {
                    Serial.printf("  Next In Queue : %s (%s)\n", nextName, nextEmpId);
                } else {
                    Serial.println("  Queue Status  : ALL CARDS FULLY ENROLLED!");
                }
                Serial.println("==================================================================\n");

                // Write sequence data to card sector 1 block 4 if enabled
                if (writeData && writeData[0] != '\0') {
                    writeSerialToCardSector(writeData);
                }

                // Add to local RAM whitelist immediately so card works offline
                if (totalCachedCards < MAX_CACHED_CARDS) {
                    int existingIdx = findCardInCache(uid);
                    int targetIdx = (existingIdx >= 0) ? existingIdx : totalCachedCards;
                    strncpy(localCardCache[targetIdx].uid, uid, sizeof(localCardCache[0].uid) - 1);
                    strncpy(localCardCache[targetIdx].name, username, sizeof(localCardCache[0].name) - 1);
                    localCardCache[targetIdx].daily_limit = limit;
                    localCardCache[targetIdx].used_today = 0;
                    if (existingIdx < 0) totalCachedCards++;
                    saveLocalCacheToNVS();
                }

                // Distinct Happy Double-Chirp Tone
                beep(2400, 80);
                delay(50);
                beep(3200, 140);

                uiDrawCardEnrolledScreen(username, empId, uid, nextName, nextEmpId, qIndex, qTotal);
                if (pulse > 0) {
                    Serial.printf("[AUTO-VEND] Dispensing item on auto-watermarked tap (pulse: %d ms)...\n", pulse);
                    triggerDispenseMotor(pulse);
                }
                delay(2200);

                if (!nextName || nextName[0] == '\0') {
                    uiDrawStandbyScreen();
                }
            } else if (authorized && strcmp(status, "DISPENSED_SUCCESS") == 0) {

                Serial.printf("[VERIFY] ✓ ACCESS GRANTED! Welcome %s (%d/%d)\n", username, used, limit);
                playSuccessTone();
                uiDrawDispenseScreen(username, used, limit, pulse);
                triggerDispenseMotor(pulse);

                // Add or update in local cache so card works offline immediately if power or Wi-Fi drops
                if (totalCachedCards < MAX_CACHED_CARDS) {
                    int existingIdx = findCardInCache(uid);
                    int targetIdx = (existingIdx >= 0) ? existingIdx : totalCachedCards;
                    strncpy(localCardCache[targetIdx].uid, uid, sizeof(localCardCache[0].uid) - 1);
                    localCardCache[targetIdx].uid[sizeof(localCardCache[0].uid) - 1] = '\0';
                    strncpy(localCardCache[targetIdx].name, username, sizeof(localCardCache[0].name) - 1);
                    localCardCache[targetIdx].name[sizeof(localCardCache[0].name) - 1] = '\0';
                    localCardCache[targetIdx].daily_limit = limit;
                    localCardCache[targetIdx].used_today = used;
                    if (existingIdx < 0) totalCachedCards++;
                    saveLocalCacheToNVS();
                }
            } else if (strcmp(status, "ENROLL_CAPTURED") == 0 || (strstr(msg, "Enroll Mode") != NULL)) {
                Serial.println("\n==================================================================");
                Serial.printf(">>> [📡 CARD CAPTURED IN LIVE ENROLL MODE] UID: %s <<<\n", uid);
                Serial.println("  Forwarded to Web Portal UI! Complete name/details in browser.");
                Serial.println("==================================================================\n");

                beep(2800, 80);
                delay(40);
                beep(3400, 120);

                uiDrawLiveCapturedScreen(uid);
                delay(2200);
                uiDrawStandbyScreen();
            } else if (strcmp(status, "DAILY_LIMIT_EXCEEDED") == 0) {
                Serial.printf("[VERIFY] ! QUOTA EXCEEDED! Limit: %d reached for %s\n", limit, username);
                playWarningTone();
                uiDrawDeniedScreen("DAILY LIMIT EXCEEDED", "No Vends Remaining");
                delay(2500);
                uiDrawStandbyScreen();
            } else if (strcmp(status, "REJECTED_NON_VENDOR") == 0) {
                Serial.printf("[VERIFY] ! REJECTED: Outside card not allowed under VENDOR_ONLY policy (%s)\n", msg);
                playErrorTone();
                uiDrawDeniedScreen("UNOFFICIAL CARD", "Use Official G-TECH Card");
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
            processOfflineTap(uid, isVendorCard);
        }
        http.end();
    }
    // ----------------------------------------------------
    // SCENARIO 2: OFFLINE MODE (No Wi-Fi / Local Fallback)
    // ----------------------------------------------------
    else {
        Serial.println("[OFFLINE MODE] Verifying against local 1,000-card RAM cache...");
        processOfflineTap(uid, isVendorCard);
    }
    Serial.println("------------------------------------------------\n");
}

// ==============================================================================
// 13. SERIAL COMMAND CONSOLE HANDLER
// ==============================================================================

void handleSerialCommand(String cmd) {
    if (cmd.startsWith("id:") || cmd.startsWith("ID:") || cmd.startsWith("dev:") || cmd.startsWith("DEV:") ||
        cmd.startsWith("rfid-") || cmd.startsWith("RFID-") || cmd.startsWith("vm-") || cmd.startsWith("VM-")) {
        int colonIdx = cmd.indexOf(':');
        String newId = (colonIdx != -1) ? cmd.substring(colonIdx + 1) : cmd;
        newId.trim();
        newId.toUpperCase();
        if (newId.length() > 0) {
            device_id = newId;
            device_token = "dev_token_" + device_id;
            prefs.begin("vending_cfg", false);
            prefs.putString("dev_id", device_id);
            prefs.putString("token", device_token);
            prefs.end();
            Serial.println("\n==================================================================");
            Serial.printf("[✓ Machine Identity Set] Device ID updated to: %s\n", device_id.c_str());
            Serial.printf("  Bound to Hardware MAC: %s\n", getDeviceMacAddress().c_str());
            Serial.println("  Saved permanently into Flash NVS! Cloud sync starting...");
            Serial.println("==================================================================\n");
            if (WiFi.status() == WL_CONNECTED) {
                authenticateWithCloud();
                syncWhitelistFromCloud();
            }
            uiDrawStandbyScreen();
        }
    } else if (cmd.startsWith("wifi:") || cmd.startsWith("WIFI:")) {
        int colonIdx = cmd.indexOf(':');
        String payload = cmd.substring(colonIdx + 1);
        payload.trim();
        int commaIdx = payload.indexOf(',');
        if (commaIdx != -1) {
            String newSsid = payload.substring(0, commaIdx);
            String newPass = payload.substring(commaIdx + 1);
            newSsid.trim();
            newPass.trim();
            wifi_ssid = newSsid;
            wifi_pass = newPass;

            prefs.begin("vending_cfg", false);
            prefs.putString("ssid", wifi_ssid);
            prefs.putString("pass", wifi_pass);
            prefs.putBool("wifi_remote", true);
            prefs.putString("code_ssid", wifi_ssid);
            prefs.end();

            Serial.println("\n==================================================================");
            Serial.printf("[✓ Wi-Fi Updated] SSID: %s\n", wifi_ssid.c_str());
            Serial.println("  Saved to Flash NVS! Rebooting to connect...");
            Serial.println("==================================================================\n");
            uiDrawWiFiUpdatingScreen(wifi_ssid);
            delay(2000);
            ESP.restart();
        } else {
            Serial.println("[!] Usage: wifi:SSID,PASSWORD");
        }
    } else if (cmd.startsWith("policy:") || cmd.startsWith("POLICY:")) {
        int colonIdx = cmd.indexOf(':');
        String val = cmd.substring(colonIdx + 1);
        val.trim();
        val.toUpperCase();
        if (val == "VENDOR_ONLY" || val == "ALLOW_ALL" || val == "1" || val == "2") {
            if (val == "1") card_policy = "VENDOR_ONLY";
            else if (val == "2") card_policy = "ALLOW_ALL";
            else card_policy = val;

            prefs.begin("vending_cfg", false);
            prefs.putString("card_pol", card_policy);
            prefs.end();
            Serial.printf("[✓ Policy Updated] Card Policy set to: %s\n", card_policy.c_str());
            uiDrawStandbyScreen();
        } else {
            Serial.println("[!] Usage: policy:VENDOR_ONLY or policy:ALLOW_ALL");
        }
    } else if (cmd.startsWith("prefix:") || cmd.startsWith("PREFIX:")) {
        int colonIdx = cmd.indexOf(':');
        String val = cmd.substring(colonIdx + 1);
        val.trim();
        val.toUpperCase();
        if (val.length() > 0) {
            vendor_prefix = val;
            prefs.begin("vending_cfg", false);
            prefs.putString("ven_pfx", vendor_prefix);
            prefs.end();
            Serial.printf("[✓ Prefix Updated] Vendor Prefix set to: %s\n", vendor_prefix.c_str());
        }
    } else if (cmd.startsWith("write:") || cmd.startsWith("WRITE:") || cmd.startsWith("watermark:") || cmd.startsWith("WATERMARK:")) {
        int colonIdx = cmd.indexOf(':');
        pendingSerialWrite = cmd.substring(colonIdx + 1);
        pendingSerialWrite.trim();
        if (pendingSerialWrite.length() > 0) {
            Serial.println("\n==================================================================");
            Serial.printf(">>> [✍️ READY TO WATERMARK CARD] Text: '%s' <<<\n", pendingSerialWrite.c_str());
            Serial.println("  Hold your RFID card flat against the reader antenna now...");
            Serial.println("==================================================================\n");
            selectTFT();
            tft.fillRoundRect(16, 100, 288, 280, 12, COLOR_CARD);
            tft.drawRoundRect(16, 100, 288, 280, 12, COLOR_YELLOW);
            tft.setCursor(45, 180);
            tft.setTextColor(COLOR_YELLOW);
            tft.setTextSize(2);
            tft.print("TAP CARD TO WRITE");
            tft.setCursor(35, 230);
            tft.setTextColor(COLOR_WHITE);
            tft.setTextSize(2);
            tft.print(pendingSerialWrite.c_str());
            deselectTFT();
        } else {
            Serial.println("[!] Usage: write:GTECH-0001 (or watermark:GTECH-0001)");
        }
    } else if (cmd == "sync" || cmd == "SYNC") {
        Serial.println("\n[⚡ SYNC] Triggering immediate whitelist & config sync from Cloud...");
        authenticateWithCloud();
        checkForRemoteConfigUpdates();
        syncWhitelistFromCloud();
    } else if (cmd == "t" || cmd == "T" || cmd.equalsIgnoreCase("test")) {
        Serial.println("\n[⚡ MOTOR TEST] Actuating dispense relay motor (1.5s)...");
        triggerDispenseMotor(1500);
    } else if (cmd == "c" || cmd == "C" || cmd.equalsIgnoreCase("wipe")) {
        Serial.println("\n[🧹 NVS] Clearing all persistent settings from Flash NVS...");
        clearPersistentConfig();
        Serial.println("[✓] NVS wiped clean! Rebooting ESP32 into Zero-Touch mode...");
        delay(500);
        ESP.restart();
    } else if (cmd == "status" || cmd == "s" || cmd == "S") {
        Serial.println("\n==================================================================");
        Serial.println(">>> 📊 MACHINE STATUS <<<");
        Serial.printf("  Hardware MAC    : %s\n", getDeviceMacAddress().c_str());
        Serial.printf("  Device ID       : %s\n", device_id.c_str());
        Serial.printf("  Active Wi-Fi    : %s (Status: %s)\n", wifi_ssid.c_str(), WiFi.status() == WL_CONNECTED ? "ONLINE" : "OFFLINE");
        if (WiFi.status() == WL_CONNECTED) {
            Serial.printf("  IP Address      : %s (RSSI: %d dBm)\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
        }
        Serial.printf("  Server URL      : %s\n", server_base_url.c_str());
        Serial.printf("  Card Policy     : %s\n", card_policy.c_str());
        Serial.printf("  Vendor Prefix   : %s\n", vendor_prefix.c_str());
        Serial.printf("  Cached Cards    : %d / %d\n", totalCachedCards, MAX_CACHED_CARDS);
        Serial.printf("  Offline Buffered: %d / %d\n", offlineBufferCount, MAX_OFFLINE_BUFFER);
        Serial.printf("  Free RAM Heap   : %u bytes\n", ESP.getFreeHeap());
        Serial.println("==================================================================\n");
    } else if (cmd == "h" || cmd == "H" || cmd == "?") {
        printHelpMenu();
    }
}

void printHelpMenu() {
    Serial.println("\n==================================================================");
    Serial.println("   GTECH RFID VENDING NODE - SERIAL COMMAND CONSOLE               ");
    Serial.println("==================================================================");
    Serial.println("  id:RFID-000001     - Set Device ID permanently into Flash NVS");
    Serial.println("  wifi:SSID,PASSWORD - Set Wi-Fi credentials & restart");
    Serial.println("  policy:VENDOR_ONLY - Set policy (VENDOR_ONLY or ALLOW_ALL)");
    Serial.println("  prefix:<PREFIX>    - Set sector watermark prefix (default: GTECH)");
    Serial.println("  write:GTECH-0001   - Write watermark signature to next tapped card");
    Serial.println("  sync               - Force immediate Cloud Handshake & Whitelist sync");
    Serial.println("  t                  - Test dispense relay motor hardware");
    Serial.println("  status             - Display live MAC, IP, network, cache & heap status");
    Serial.println("  wipe               - Clear all Flash NVS persistent config & reboot");
    Serial.println("  ? or h             - Show this help menu");
    Serial.println("==================================================================\n");
}

// ==============================================================================
// 14. SETUP & INITIALIZATION
// ==============================================================================

void setup() {
    // 1. Critical Boot Glitch Protection: Clamp Motor Relay to OFF immediately
    pinMode(PIN_RELAY_MOTOR, OUTPUT);
    digitalWrite(PIN_RELAY_MOTOR, LOW); // Relay strictly OFF

    pinMode(PIN_BUZZER, OUTPUT);
    digitalWrite(PIN_BUZZER, LOW);

    // Setup Chip Select pins to inactive (HIGH)
    pinMode(RFID_SS_PIN, OUTPUT);
    digitalWrite(RFID_SS_PIN, HIGH);

    pinMode(TFT_CS_PIN, OUTPUT);
    digitalWrite(TFT_CS_PIN, HIGH);

    Serial.begin(115200);
    delay(200);

    // 2. Load persistent configuration & cached data from Flash NVS
    loadPersistentConfig();
    loadLocalCacheFromNVS();
    loadOfflineBufferFromNVS();

    // Initial audio chirp
    beep(2000, 100);

    // 3. Initialize Hardware SPI Bus
    SPI.begin(SPI_SCK_PIN, SPI_MISO_PIN, SPI_MOSI_PIN, RFID_SS_PIN);

    // 4. Initialize ILI9488 TFT LCD Display
    Serial.println("[TFT] Initializing 320x480 ILI9488 SPI LCD Display...");
    selectTFT();
    tft.begin();
    tft.setRotation(TFT_ROTATION); // Vertical Portrait
    deselectTFT();

    // Show initial boot animation screen
    uiDrawBootScreen();
    delay(1200);

    // 5. Initialize MFRC522 RFID reader
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

    // 6. Connect to Wi-Fi
    uiDrawWiFiConnectingScreen(wifi_ssid.c_str());
    Serial.printf("[WIFI] Connecting to '%s'...\n", wifi_ssid.c_str());
    WiFi.mode(WIFI_STA);
    WiFi.begin(wifi_ssid.c_str(), wifi_pass.c_str());

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

        // 7. Cloud Gateway Handshake (Authenticates via hardware MAC & binds correct Device ID dynamically)
        authenticateWithCloud();
        checkForRemoteConfigUpdates();
        syncWhitelistFromCloud();
        flushOfflineBufferToCloud(); // Immediately sync any pending offline vends from Flash
    } else {
        Serial.println("\n[WIFI] ! Wi-Fi Connection Failed. Running in OFFLINE CACHE MODE.");
        playWarningTone();
    }

    // Draw main operational standby screen or pending discovery pairing screen
    uiDrawStandbyScreen();
    printHelpMenu();
    Serial.println("\n[READY] Vending Machine Node Active.\n");
}

// ==============================================================================
// 15. MAIN LOOP
// ==============================================================================

void loop() {
    unsigned long currentMillis = millis();

    // 1. Interactive USB Serial Command Console
    if (Serial.available()) {
        String cmd = Serial.readStringUntil('\n');
        cmd.trim();
        if (cmd.length() > 0) {
            handleSerialCommand(cmd);
        }
    }

    // 2. Maintain Wi-Fi, Heartbeat & Remote Cloud Config Poll
    if (WiFi.status() == WL_CONNECTED) {
        if (!isWifiConnected) {
            isWifiConnected = true;
            Serial.println("[WIFI] * Reconnected to Internet!");
            playSuccessTone();
            authenticateWithCloud();
            uiDrawStandbyScreen();
            flushOfflineBufferToCloud();
            syncWhitelistFromCloud();
        }

        // Adaptive polling: Check every 3 seconds if waiting for Claim (Zero-Touch discovery),
        // or every 60 seconds once active and registered!
        unsigned long pollInterval = (device_id == "AUTO" || device_id == "PENDING") ? DISCOVERY_POLL_MS : HEARTBEAT_INTERVAL_MS;

        if (currentMillis - lastHeartbeatTime >= pollInterval) {
            lastHeartbeatTime = currentMillis;
            checkForRemoteConfigUpdates();
        }

        // Periodic whitelist sync every 5 minutes (only when active)
        if (device_id != "AUTO" && device_id != "PENDING" && (currentMillis - lastCardSyncTime > SYNC_INTERVAL_MS)) {
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

    // 3. Check for RFID Card Tap (Only when machine is active, not in discovery mode)
    if (device_id == "AUTO" || device_id == "PENDING" || device_id.length() == 0) {
        delay(50);
        return;
    }

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
    deselectRFID();


    // Check if user initiated a manual watermark write from Serial Console
    if (pendingSerialWrite.length() > 0) {
        Serial.printf("[MANUAL WRITE] Writing watermark '%s' into Sector 1 Block 4 of card %s...\n", pendingSerialWrite.c_str(), uidString);
        bool writeSuccess = writeSerialToCardSector(pendingSerialWrite.c_str());
        if (writeSuccess) {
            playSuccessTone();
            Serial.printf("[✓ SUCCESS] Watermark '%s' permanently saved to card Sector 1 Block 4!\n\n", pendingSerialWrite.c_str());
            uiDrawCardEnrolledScreen("Official Card", pendingSerialWrite.c_str(), uidString, "", "", 1, 1);
            delay(2200);
            uiDrawStandbyScreen();
        } else {
            playErrorTone();
            Serial.println("[!] Watermark write failed! Card might be read-only or moved too quickly.\n");
            uiDrawDeniedScreen("WRITE FAILED", "Try Again");
            delay(2200);
            uiDrawStandbyScreen();
        }
        pendingSerialWrite = "";
        selectRFID();
        rfid.PICC_HaltA();
        rfid.PCD_StopCrypto1();
        deselectRFID();
        delay(1000);
        return;
    }

    // Read Sector 1 Block 4 for proprietary vendor watermark signature
    char sectorData[32] = {0};
    bool sectorReadSuccess = readSerialFromCardSector(sectorData, sizeof(sectorData));
    bool isVendorCard = false;
    if (sectorReadSuccess && strlen(sectorData) > 0) {
        if (vendor_prefix.length() > 0 && strncmp(sectorData, vendor_prefix.c_str(), vendor_prefix.length()) == 0) {
            isVendorCard = true;
        }
    }
    deselectRFID();

    // Process the tapped card with full TFT display feedback and policy enforcement
    processCardTap(uidString, isVendorCard, sectorData);

    // Halt PICC and stop crypto after tap processing and writing is finished
    selectRFID();
    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();
    deselectRFID();


    // Debounce pause so single tap doesn't double-trigger
    delay(1000);
}
