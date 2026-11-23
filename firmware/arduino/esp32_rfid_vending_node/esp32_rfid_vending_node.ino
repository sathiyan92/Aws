/*
 * ==============================================================================
 * GTECH SMART IOT FLEET PLATFORM
 * Node Type: ESP32 RFID Card-Based Vending Machine Controller
 * File: esp32_rfid_vending_node.ino
 * Firmware: v2.5.0-rfid-tft-nvs
 * ==============================================================================
 * Features:
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

// Machine Identifier mapped in cloud database (RFID-000001)
String device_id       = "RFID-000001";
String device_token    = "dev_token_RFID-000001";

int current_config_version = 1;

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

// State flags and timing
bool isWifiConnected = false;
unsigned long lastHeartbeatTime = 0;
unsigned long lastCardSyncTime = 0;
const unsigned long SYNC_INTERVAL_MS = 300000; // Auto-sync whitelist every 5 minutes
const unsigned long HEARTBEAT_INTERVAL_MS = 60000; // Heartbeat & remote config poll every 60 seconds

// Hardware Driver Objects
DIYables_ILI9488_SPI tft(TFT_WIDTH, TFT_HEIGHT, TFT_CS_PIN, TFT_DC_PIN, TFT_RST_PIN);
MFRC522 rfid(RFID_SS_PIN, RFID_RST_PIN);

// Forward Declarations
void printHelpMenu();
void handleSerialCommand(String cmd);
void syncWhitelistFromCloud();
void checkForRemoteConfigUpdates();
void sendHeartbeat();
void uiDrawStandbyScreen();

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

    // --- SMART WI-FI SELECTION (Same as QR Machine) ---
    // 1. If configured via Cloud Web Portal or Serial, always honor it:
    if (has_remote_wifi && saved_ssid.length() > 0) {
        wifi_ssid = saved_ssid;
        wifi_pass = saved_pass;
        Serial.printf("[Config] 📶 Cloud/Saved Wi-Fi active: %s\n", wifi_ssid.c_str());
    } else if (wifi_ssid.length() > 0 && wifi_ssid != last_code_ssid) {
        // 2. If developer updated credentials in sketch code, persist to Flash NVS:
        prefs.putString("ssid", wifi_ssid);
        prefs.putString("pass", wifi_pass);
        prefs.putString("code_ssid", wifi_ssid);
        Serial.printf("[Config] ⭐ New Wi-Fi from sketch code detected & applied: %s\n", wifi_ssid.c_str());
    } else if (saved_ssid.length() > 0) {
        // 3. Fallback to saved
        wifi_ssid = saved_ssid;
        wifi_pass = saved_pass;
    }

    if (saved_url.length() > 0) {
        server_base_url = saved_url;
    }

    // Machine ID loading
    if (saved_dev_id.length() > 0) {
        device_id = saved_dev_id;
        device_token = prefs.getString("token", "dev_token_" + device_id);
        Serial.printf("[Config] 💾 Machine ID loaded from Flash NVS: %s\n", device_id.c_str());
    } else {
        // Save initial default
        prefs.putString("dev_id", device_id);
        prefs.putString("token", device_token);
    }
    prefs.end();

    Serial.println("\n==================================================================");
    Serial.println("  >>> ⚡ GTECH ESP32 RFID VENDING CONTROLLER NODE <<<            ");
    Serial.println("==================================================================");
    Serial.printf("  Device ID (Machine)  : %s\n", device_id.c_str());
    Serial.printf("  Target Wi-Fi SSID    : %s\n", wifi_ssid.c_str());
    Serial.printf("  Cloud Server Base URL: %s\n", server_base_url.c_str());
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
    Serial.println("[!] Flash NVS wiped.");
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
    tft.print("Machine ID    : ");
    tft.setTextColor(COLOR_CYAN);
    tft.println(device_id);

    tft.setCursor(30, 245);
    tft.setTextColor(COLOR_WHITE);
    tft.print("Firmware      : v2.5.0-rfid-tft-nvs");

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

void uiDrawWiFiUpdatingScreen(const String& newSsid) {
    selectTFT();
    tft.fillScreen(COLOR_BG);

    // Top Header Banner
    tft.fillRect(0, 0, TFT_WIDTH, 55, COLOR_HEADER);
    tft.drawFastHLine(0, 55, TFT_WIDTH, COLOR_CYAN);

    tft.setCursor(20, 18);
    tft.setTextColor(COLOR_CYAN);
    tft.setTextSize(2);
    tft.print("CLOUD WI-FI UPDATE");

    // Main Card
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
    tft.printf("NODE: %s  |  MODE: RFID CARD TAP", device_id.c_str());

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
// 9. MOTOR RELAY CONTROL
// ==============================================================================

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
// 10. CACHE MANAGEMENT & CLOUD SYNC (1,000 Cards)
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
                if (cloudDev.length() > 0 && cloudDev != device_id) {
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
    String endpoint = server_base_url + "/api/v1/orders/qr-config/" + device_id;
    http.setTimeout(4000);
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
                if (cloudDev.length() > 0 && cloudDev != device_id) {
                    Serial.printf("[Config] 🏷️ Machine ID updated from Cloud: %s -> %s\n", device_id.c_str(), cloudDev.c_str());
                    device_id = cloudDev;
                    device_token = "dev_token_" + device_id;
                    prefs.begin("vending_cfg", false);
                    prefs.putString("dev_id", device_id);
                    prefs.putString("token", device_token);
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

void sendHeartbeat() {
    if (WiFi.status() != WL_CONNECTED) return;
    checkForRemoteConfigUpdates();
}

void flushOfflineBufferToCloud() {
    if (offlineBufferCount == 0 || WiFi.status() != WL_CONNECTED) return;

    Serial.printf("[OFFLINE] Flushing %d buffered offline vends to Cloud...\n", offlineBufferCount);
    HTTPClient http;
    String url = server_base_url + "/api/v1/rfid-vending/offline-sync";

    DynamicJsonDocument doc(4096);
    doc["device_id"] = device_id;
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
// 11. CARD TAP PROCESSOR (ONLINE & OFFLINE)
// ==============================================================================

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
        String url = server_base_url + "/api/v1/rfid-vending/verify-tap";
        http.begin(url);
        http.addHeader("Content-Type", "application/json");
        http.setTimeout(4000);

        StaticJsonDocument<256> doc;
        doc["device_id"] = device_id;
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
// 12. SERIAL COMMAND CONSOLE HANDLER
// ==============================================================================

void handleSerialCommand(String cmd) {
    if (cmd.startsWith("id:") || cmd.startsWith("ID:") || cmd.startsWith("dev:") || cmd.startsWith("DEV:")) {
        int colonIdx = cmd.indexOf(':');
        String newId = cmd.substring(colonIdx + 1);
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
            Serial.println("  Saved permanently into Flash NVS! Whitelist sync starting...");
            Serial.println("==================================================================\n");
            if (WiFi.status() == WL_CONNECTED) {
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
    } else if (cmd == "sync" || cmd == "SYNC") {
        Serial.println("\n[⚡ SYNC] Triggering immediate whitelist & config sync from Cloud...");
        syncWhitelistFromCloud();
        checkForRemoteConfigUpdates();
    } else if (cmd == "t" || cmd == "T" || cmd.equalsIgnoreCase("test")) {
        Serial.println("\n[⚡ MOTOR TEST] Actuating dispense relay motor (1.5s)...");
        triggerDispenseMotor(1500);
    } else if (cmd == "c" || cmd == "C" || cmd.equalsIgnoreCase("wipe")) {
        Serial.println("\n[🧹 NVS] Clearing all persistent settings from Flash NVS...");
        prefs.begin("vending_cfg", false);
        prefs.clear();
        prefs.end();
        Serial.println("[✓] NVS wiped clean! Rebooting ESP32...");
        delay(500);
        ESP.restart();
    } else if (cmd == "status" || cmd == "s" || cmd == "S") {
        Serial.println("\n==================================================================");
        Serial.println(">>> 📊 MACHINE STATUS <<<");
        Serial.printf("  Device ID       : %s\n", device_id.c_str());
        Serial.printf("  Active Wi-Fi    : %s (Status: %s)\n", wifi_ssid.c_str(), WiFi.status() == WL_CONNECTED ? "ONLINE" : "OFFLINE");
        if (WiFi.status() == WL_CONNECTED) {
            Serial.printf("  IP Address      : %s (RSSI: %d dBm)\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
        }
        Serial.printf("  Server URL      : %s\n", server_base_url.c_str());
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
    Serial.println("  sync               - Force immediate Cloud Whitelist & Config sync");
    Serial.println("  t                  - Test dispense relay motor hardware");
    Serial.println("  status             - Display live network, IP, cache & heap status");
    Serial.println("  wipe               - Clear all Flash NVS persistent config & reboot");
    Serial.println("  ? or h             - Show this help menu");
    Serial.println("==================================================================\n");
}

// ==============================================================================
// 13. SETUP & INITIALIZATION
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

    // 2. Load persistent configuration from Flash NVS
    loadPersistentConfig();

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

        // Initial whitelist download & remote config check
        syncWhitelistFromCloud();
        checkForRemoteConfigUpdates();
    } else {
        Serial.println("\n[WIFI] ! Wi-Fi Connection Failed. Running in OFFLINE CACHE MODE.");
        playWarningTone();
    }

    // Draw main operational standby screen
    uiDrawStandbyScreen();
    printHelpMenu();
    Serial.println("\n[READY] Vending Machine is Ready. Tap an RFID card to vend!\n");
}

// ==============================================================================
// 14. MAIN LOOP
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
            uiDrawStandbyScreen();
            flushOfflineBufferToCloud();
            syncWhitelistFromCloud();
        }

        // Heartbeat & Remote Cloud Config Poll every 60 seconds
        if (currentMillis - lastHeartbeatTime > HEARTBEAT_INTERVAL_MS) {
            lastHeartbeatTime = currentMillis;
            sendHeartbeat();
        }

        // Periodic whitelist sync every 5 minutes
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

    // 3. Check for RFID Card Tap
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
