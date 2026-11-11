/**
 * ==============================================================================
 * ESP32 VENDING MACHINE: DUAL-MODE (WITH STOCK & WITHOUT STOCK)
 * VERTICAL PORTRAIT TFT LCD (320x480) + DUAL PUSH BUTTONS + DROP SENSOR
 * ==============================================================================
 * Multi-Tenant IoT Fleet Platform (Scale to 1,000+ Machines)
 * Target Board: ESP32 / ESP32-WROOM-32 / ESP32-S3
 * Display: 3.5" or 4.0" ILI9488 320x480 TFT LCD (SPI Interface) - VERTICAL PORTRAIT
 * Orientation: Portrait (320 Wide x 480 High)
 * Motor: Vending Dispense Motor / Relay (Configured for 1 Motor, expandable to 2+)
 * 
 * NEW FEATURES & OPERATING MODES:
 * ------------------------------------------------------------------------------
 * 1. PHYSICAL COIN ACCEPTOR INPUT & PULSE MIRRORING:
 *    - Coin Input Pin (GPIO 13, INPUT_PULLUP): Receives pulses from coin acceptor.
 *    - Mirrored Coin Output (GPIO 25): Every incoming pulse received on GPIO 13
 *      is mirrored/echoed in real-time onto GPIO 25 for master board / auditor logging.
 *    - Coin Triggered Dispense: Whenever coin pulses are received, the machine vends!
 * 
 * 2. WEB-CONTROLLED PAYMENT ACCEPTANCE MODES:
 *    - Mode 1 ("QR_ONLY")  : Operates exclusively with Dynamic Razorpay UPI QR codes.
 *    - Mode 2 ("COIN_ONLY"): Operates exclusively with Physical Coin Acceptor.
 *    - Mode 3 ("BOTH")     : Hybrid mode! Customer can scan QR OR insert coins.
 *    - Controlled dynamically from the Website Portal (instant sync via cloud poll).
 * 
 * 3. DUAL MACHINE MODE (Stock-Based vs Without-Stock):
 *    - Mode A (Stock-Based): Tracks inventory (1-50 units). When stock hits 0,
 *      machine displays "OUT OF STOCK" screen and pauses vending until refilled.
 *    - Mode B (Without Stock): Continuous unlimited vending (no inventory limit).
 * 
 * 2. TWO PHYSICAL PUSH SWITCHES FOR IN-FIELD STOCK MANAGEMENT:
 *    - Push Switch 1 (GPIO 32 - Cycle Stock): Pressing increments stock count
 *      from 1 to 50, then automatically wraps back to 1!
 *    - Push Switch 2 (GPIO 33 - Save Stock): Pressing saves the selected stock
 *      directly to Flash NVS memory, updates the LCD, and reports to AWS Cloud.
 *    - Mode Toggle: Holding Push Switch 2 for 4 seconds toggles between
 *      Stock-Based Mode and Without-Stock Mode directly on the machine!
 * 
 * 3. MATERIAL DISPENSE DETECTION SENSOR (GPIO 14):
 *    - Optical / IR Beam-Break / Drop Sensor verifies that the product has
 *      physically fallen through the drop chute.
 *    - Automatically shuts off motor once material is detected.
 *    - Detects empty slot / motor jam if no material passes within timeout.
 * 
 * Architecture (No Buttons - Scan & Vend by Price):
 * ------------------------------------------------------------------------------
 * 1. Screen permanently displays the machine's Razorpay UPI QR Code on standby.
 * 2. Customer opens PhonePe / GPay / Paytm / BHIM, scans QR, and pays (e.g. ₹10.00).
 * 3. Razorpay captures payment -> Fires Cloud Webhook -> Splits/Transfers funds
 *    to the Client/Vendor's Linked Account via Razorpay Route.
 * 4. Cloud matches payment amount (₹10.00) to physical Slot/Motor 1.
 * 5. ESP32 polls cloud -> Detects authorized payment -> Runs Motor 1!
 * 6. Display dynamically updates to:
 *    - "PAYMENT VERIFIED: ₹10.00"
 *    - "VENDING IN PROGRESS..."
 *    - "PLEASE COLLECT MATERIAL"
 *    - Smooth animated progress bar during motor cycle.
 * 7. Screen shows "DISPENSE COMPLETED! PLEASE COLLECT MATERIAL FROM TRAY" for 4s.
 * 8. Machine decrements stock in cloud and returns to Standby QR Screen.
 * 
 * Hardware Wiring:
 * ------------------------------------------------------------------------------
 * ILI9488 TFT LCD (SPI):
 *   VCC        ->  3.3V (Do NOT connect to 5V!)
 *   GND        ->  GND
 *   CS         ->  GPIO 5  (TFT_CS_PIN)
 *   RESET      ->  GPIO 4  (TFT_RST_PIN)
 *   DC / RS    ->  GPIO 2  (TFT_DC_PIN)
 *   SDI / MOSI ->  GPIO 23 (Hardware SPI MOSI)
 *   SCK        ->  GPIO 18 (Hardware SPI SCK)
 *   SDO / MISO ->  GPIO 19 (Optional, VSPI MISO)
 *   LED / BL   ->  3.3V (Backlight power)
 * 
 * Motors & Pulse Pins:
 *   Motor 1 (Slot 1 Relay / Driver)      -> GPIO 26
 *   Motor 2 (Slot 2 Relay / Driver)      -> GPIO 27 (Optional secondary motor)
 *   Coin Pulse Output Pin (Mirrored Out) -> GPIO 25 (Mirrors coin pulses & QR pulses)
 *   Coin Acceptor Pulse Input Pin        -> GPIO 13 (Pulses from electronic coin acceptor)
 *   Dispense Drop Sensor (Chute Beam)    -> GPIO 14 (IR / Microswitch material detect)
 *   Push Switch 1 (Cycle Stock 1-50)     -> GPIO 32
 *   Push Switch 2 (Select / Save Stock)  -> GPIO 33
 * 
 * Control & Bench Test:
 *   BOOT Button -> GPIO 0 (Press to cancel / Hold 5s for Wi-Fi factory reset)
 *   Serial Monitor (115200 Baud):
 *     'p' -> Simulate instant ₹10.00 Razorpay payment (Triggers motor & LCD)
 *     't' -> Hardware Motor Test (Runs Motor 1 for 1.5s)
 * ==============================================================================
 */

#include <WiFi.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <Preferences.h>
#include <HTTPClient.h>
#include <Update.h>
#include <ArduinoJson.h>
#include <DIYables_TFT_SPI.h>
#include "qrcode.h"

// ------------------------------------------------------------------------------
// HARDWARE MAC & SILICON CHIP ID UTILITY
// ------------------------------------------------------------------------------
// Reads MAC directly using Arduino core (compatible with all ESP32 / S2 / S3 / C3 board versions)
String getDeviceMacAddress() {
  WiFi.mode(WIFI_STA);
  String mac = WiFi.macAddress();
  if (mac.length() == 17 && mac != "00:00:00:00:00:00") {
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
// TFT SPI Pins (ILI9488)
#define TFT_CS_PIN    5
#define TFT_DC_PIN    2
#define TFT_RST_PIN   4
#define TFT_WIDTH     320
#define TFT_HEIGHT    480

// ------------------------------------------------------------------------------
// DISPLAY ORIENTATION (VERTICAL / PORTRAIT)
// ------------------------------------------------------------------------------
// Set TFT_ROTATION to 0 for standard vertical portrait (320x480).
// Set to 2 if your screen is mounted rotated 180 degrees.
#define TFT_ROTATION  0

// Motor / Relay Pins (Default: Working with 1 Motor on GPIO 26)
const int PIN_MOTOR_SLOT_1  = 26;   // Motor 1 Relay / Driver IN1
const int PIN_MOTOR_SLOT_2  = 27;   // Motor 2 (Optional secondary motor)
const int PIN_COIN_PULSE_OUT = 25;  // Coin Pulse Output Pin (Generates pulses based on QR amount)
const int PIN_SETUP_BTN     = 0;    // ESP32 BOOT Button (Hold 3s for Wi-Fi Hotspot)

// ==============================================================================
// 1b. DUAL PUSH SWITCHES & MATERIAL DISPENSE DETECTION SENSOR
// ==============================================================================
// Push Switch 1: Increments stock from 1 to 50, then wraps back to 1
const int PIN_STOCK_INC_BTN    = 32;  // Push Button 1 (INPUT_PULLUP to GND)

// Push Switch 2: Confirms & saves stock into Flash NVS (Hold 4s to toggle Stock Mode)
const int PIN_STOCK_SAVE_BTN   = 33;  // Push Button 2 (INPUT_PULLUP to GND)

// Material Dispense Sensor: Detects item dropping through the chute
const int PIN_DISPENSE_SENSOR  = 14;  // IR Beam Break / Optical / Microswitch (INPUT_PULLUP)
const int PIN_COIN_INPUT        = 13;  // Electronic Coin Acceptor Pulse Input (INPUT_PULLUP, GPIO 13 or 34/35)

// COIN ACCEPTOR INPUT TIMING & POLARITY
#define COIN_INPUT_ACTIVE_LOW       1     // 1 for Active-LOW (pulls LOW on pulse), 0 for Active-HIGH
const unsigned long COIN_INPUT_MIN_PULSE_MS     = 15;   // Rejects noise spikes < 15ms
const unsigned long COIN_INPUT_MAX_PULSE_MS     = 250;  // Rejects stuck pulses > 250ms
const unsigned long COIN_INPUT_IDLE_TIMEOUT_MS  = 300;  // 300ms after last pulse -> pulse train complete!

// Sensor Polarity: true = LOW when material detected (Standard IR Obstacle / Beam sensor)
#define DISPENSE_SENSOR_ACTIVE_LOW    true
// Set true to enforce drop detection during vend, false for timer-only vend
#define DISPENSE_SENSOR_ENABLED       true
// Maximum time (ms) to wait for product to drop before declaring jam / empty
const unsigned long DISPENSE_SENSOR_TIMEOUT_MS = 5000;

// ==============================================================================
// 1c. STOCK MANAGEMENT CONFIGURATION (SWITCHABLE MODE)
// ==============================================================================
// Set true  -> Machine operates in STOCK-BASED MODE (tracks quantity, halts at 0)
// Set false -> Machine operates in WITHOUT-STOCK MODE (infinite continuous vending)
#define ENABLE_STOCK_MANAGEMENT       true

// Maximum stock quantity selectable via push button (1 to 50)
const int MAX_SELECTABLE_STOCK        = 50;
const int DEFAULT_INITIAL_STOCK       = 10;

// Dispense Runtime (Milliseconds)
const unsigned long MOTOR_DISPENSE_TIME_MS = 3000; // Motor runs for 3 seconds per dispense

// ==============================================================================
// COIN PULSE CONFIGURATION (TIMING & POLARITY)
// Generates coin pulses based on QR amount at the SAME TIME as Motor 1 runs!
// ==============================================================================
#define COIN_PULSE_ACTIVE_LOW      0     // Set 0 for Active-HIGH (0V idle, 3.3V pulse), 1 for Active-LOW (3.3V idle, 0V pulse)
const int COIN_PULSE_WIDTH_MS      = 50;  // Pulse ON duration (50ms standard)
const int COIN_PULSE_GAP_MS        = 50;  // Pulse OFF duration between pulses (50ms standard)
const float COIN_VALUE_PER_PULSE   = 1.0; // Rs 1.00 per pulse (e.g. Rs 1 = 1 pulse, Rs 2 = 2 pulses, Rs 5 = 5 pulses)

// ==============================================================================
// 2. RELAY POLARITY CONFIGURATION
// ==============================================================================
// Set RELAY_ACTIVE_LOW to 1 if your relay module is Active-LOW (trigger on LOW).
// Set RELAY_ACTIVE_LOW to 0 if your relay / driver is Active-HIGH (trigger on HIGH).
#define RELAY_ACTIVE_LOW 0

// Number of Active Motors connected (1 or 2)
#define ACTIVE_MOTOR_COUNT 1

// ==============================================================================
// 3. COLOR DEFINITIONS (16-bit RGB565)
// ==============================================================================
#define COLOR_BG          DIYables_TFT_SPI::colorRGB(11, 17, 32)     // Dark Navy Slate (#0B1120)
#define COLOR_CARD        DIYables_TFT_SPI::colorRGB(26, 36, 56)     // Slate Card (#1A2438)
#define COLOR_CARD_BORDER DIYables_TFT_SPI::colorRGB(51, 65, 85)     // Slate Border (#334155)
#define COLOR_HEADER      DIYables_TFT_SPI::colorRGB(15, 23, 42)     // Header background
#define COLOR_WHITE       DIYables_TFT_SPI::colorRGB(255, 255, 255)
#define COLOR_BLACK       DIYables_TFT_SPI::colorRGB(0, 0, 0)
#define COLOR_CYAN        DIYables_TFT_SPI::colorRGB(6, 182, 212)    // Neon Cyan (#06B6D4)
#define COLOR_BLUE        DIYables_TFT_SPI::colorRGB(14, 165, 233)   // Sky Blue (#0EA5E9)
#define COLOR_GREEN       DIYables_TFT_SPI::colorRGB(16, 185, 129)   // Emerald Green (#10B981)
#define COLOR_AMBER       DIYables_TFT_SPI::colorRGB(245, 158, 11)   // Warning Gold (#F59E0B)
#define COLOR_YELLOW      DIYables_TFT_SPI::colorRGB(250, 204, 21)   // Bright Yellow (#FACC15)
#define COLOR_ORANGE      DIYables_TFT_SPI::colorRGB(249, 115, 22)   // Vibrant Orange (#F97316)
#define COLOR_RED         DIYables_TFT_SPI::colorRGB(239, 68, 68)    // Coral Red (#EF4444)
#define COLOR_GRAY        DIYables_TFT_SPI::colorRGB(148, 163, 184)  // Slate Muted (#94A3B8)
#define COLOR_DARK_GRAY   DIYables_TFT_SPI::colorRGB(30, 41, 59)

// Create Display Object for ILI9488
DIYables_ILI9488_SPI TFT_display(TFT_WIDTH, TFT_HEIGHT, TFT_CS_PIN, TFT_DC_PIN, TFT_RST_PIN);

// ==============================================================================
// 4. CONFIGURATION & STATE STORAGE (FLASH NVS)
// ==============================================================================
Preferences prefs;

// ==============================================================================
// ⭐ STATIC PROGRAM QR & PRODUCT CONFIGURATION (ALTER HERE IN ARDUINO IDE)
// ==============================================================================
// When FORCE_STATIC_PROGRAM_CONFIG is true:
// - Altering the 3 lines below and clicking "Upload" in Arduino IDE will IMMEDIATELY
//   display your new QR code, Product Name, and Price on the physical LCD screen!
// - It permanently updates Flash NVS memory so your changes never get wiped.
// - Cloud polling will NOT overwrite or revert your QR code on screen.
//
// Set FORCE_STATIC_PROGRAM_CONFIG to false if you want the QR code to be controlled
// dynamically via the Web Dashboard / Cloud.
// ==============================================================================
#define FORCE_STATIC_PROGRAM_CONFIG   false  // Set true to use values below, false for web portal control //true for program link for razorpay

const char* STATIC_QR_CODE      = "upi://pay?am=1.00&cu=INR&mc=5300&mode=19&pa=gtech282722.rzp@rxairtel&tn=Payment%20To%20GTECH&tr=TuoZnOxKYLXaLvqrv2";
const char* STATIC_TR_ID        = "TuoZnOxKYLXaLvqrv2"; // Machine's unique Razorpay QR ID
const char* STATIC_PRODUCT_NAME = "G-TECH Test";
const float STATIC_PRICE_RUPEES = 1.00;

// Set to true if you want to bypass QR string encoding and draw the raw 2D pixel bitmap:
#define USE_CUSTOM_STATIC_BITMAP      false

String wifi_ssid        = "IOTHUB";
String wifi_pass        = "IOTHUB07";
String device_id        = "VM-000001";              // Unique Machine ID in 1000+ fleet
String device_token     = "dev_token_VM-000001";
String server_base_url  = "http://35.154.219.82:8000";
String razorpay_upi_vpa = "gtech282722.rzp@rxairtel"; // Default GTECH Standee Razorpay VPA
String firmware_version = "v2.2.0-razorpay-ota";

// Cloud Session & Online State
String session_jwt      = "";
bool   is_authenticated = false;

// Stock State Machine
bool stock_management_enabled = ENABLE_STOCK_MANAGEMENT;
int  current_stock            = DEFAULT_INITIAL_STOCK;
int  refill_stock_count       = DEFAULT_INITIAL_STOCK;

// PAYMENT ACCEPTANCE MODE (QR_ONLY, COIN_ONLY, BOTH)
// Controlled from the Website Portal in real time or via NVS Flash
String payment_mode = "BOTH"; // "BOTH", "QR_ONLY", "COIN_ONLY"

// COIN ACCEPTOR INTERRUPT / PULSE STATE
volatile unsigned long isr_last_coin_pulse_time = 0;
volatile int isr_coin_pulses_received = 0;
volatile bool isr_new_coin_pulse = false;

void IRAM_ATTR isrCoinAcceptorPulse() {
  unsigned long now = millis();
  if (now - isr_last_coin_pulse_time >= COIN_INPUT_MIN_PULSE_MS) {
    isr_coin_pulses_received++;
    isr_last_coin_pulse_time = now;
    isr_new_coin_pulse = true;
  }
}
bool is_refill_mode           = false;
unsigned long last_refill_activity_time = 0;
const unsigned long REFILL_TIMEOUT_MS   = 25000; // 25s auto-exit from refill menu if idle

// Machine Operating State Machine
enum MachineState {
  STATE_STANDBY_QR,    // Continuously displaying QR, polling for payment
  STATE_DISPENSING,    // Payment confirmed, motor running, showing collect material
  STATE_COMPLETE,      // Dispense complete screen
  STATE_OTA_UPDATING   // Downloading and flashing firmware wirelessly
};
MachineState current_state = STATE_STANDBY_QR;

// Live Network & Internet Status Monitoring
enum NetworkStatus {
  NET_STATUS_ONLINE,       // Wi-Fi connected + AWS Cloud reachable (Green)
  NET_STATUS_NO_WIFI,      // Wi-Fi disconnected from router/AP (Red)
  NET_STATUS_NO_INTERNET   // Wi-Fi connected, but Internet / AWS Cloud unreachable (Amber)
};
NetworkStatus current_net_status = NET_STATUS_NO_WIFI;
int consecutive_cloud_fails = 0;

// Dispense Order Details
String pending_order_id     = "";
String pending_order_number = "";
int    pending_slot_number  = 1;
float  pending_amount_rupee = 2.00;
String pending_product_name = "G-TECH Test";
String custom_qr_code       = "upi://pay?am=2.00&cu=INR&mc=5300&mode=19&pa=gtech282722.rzp@rxairtel&tn=Payment%20To%20GTECH&tr=TuXKipEEX2KteFqrv2";
String dynamic_tr_id        = ""; // Dynamically synced TR ID from cloud portal
String last_dispensed_order_id = ""; // Flash-persisted order ID to prevent duplicate vends across resets

// Polling intervals
unsigned long last_poll_time = 0;
const unsigned long POLL_INTERVAL_MS = 1800; // Check cloud for Razorpay payment every 1.8 seconds

// Remote Config Polling (Checks if Vendor/Manufacturer changed QR or Price)
unsigned long last_config_check_time = 0;
const unsigned long CONFIG_CHECK_INTERVAL_MS = 5000;  // Fast 5-second cloud sync for instant screen refresh
int current_config_version = 1;

// Over-The-Air (OTA) Polling
unsigned long last_ota_check_time = 0;
const unsigned long OTA_CHECK_INTERVAL_MS = 20000; // Check for pending OTA updates every 20s

// Periodic Health Heartbeat
unsigned long last_heartbeat_time = 0;
const unsigned long HEARTBEAT_INTERVAL_MS = 45000; // Send telemetry heartbeat every 45s

// Fallback Captive Portal for Initial Wi-Fi Setup
WebServer webServer(80);
DNSServer dnsServer;
bool in_ap_setup_mode = false;

// Forward Declarations
void uiDrawStandbyQRScreen();
void uiDrawOutOfStockNotice();
void uiDrawStockRefillScreen(int count);
void uiDrawStockSavedScreen(int count);
void uiDrawModeToggledScreen(bool stockModeOn);
void uiDrawWiFiConnectingScreen(const String& ssid);
void uiDrawWiFiConnectedScreen(const String& ssid, const String& ip);
void uiDrawWiFiSetupScreen(const String& apName, const String& ipAddress);
void uiDrawVendingScreen(int slotNumber, float amount, String productName);
void uiDrawCompleteScreen();
void uiUpdateNetworkStatus(NetworkStatus newStatus);
void uiDrawOfflineNotice(NetworkStatus status);
void setMotor(int slotNumber, bool turnOn);
void setCoinPulsePin(bool active);
void dispenseProduct(int slotNumber, float amount, String orderId, String dispenseToken = "", String productName = "");
void confirmDispenseToCloud(String orderId, String dispenseToken = "");
void pollPendingDispense();
void testMotorHardware();
void printHelpMenu();
bool authenticateWithCloud();
void sendHeartbeat();
void checkForPendingOTA();
bool performOTA(String downloadUrl, String deploymentId, size_t binarySize, String targetVer);
void reportOTAStatus(String deploymentId, String status, String errorMsg = "");

// ==============================================================================
// 5. MOTOR CONTROL HELPER
// ==============================================================================
void setMotor(int slotNumber, bool turnOn) {
  int pin = (slotNumber == 2 && ACTIVE_MOTOR_COUNT > 1) ? PIN_MOTOR_SLOT_2 : PIN_MOTOR_SLOT_1;
  int state = turnOn ? (RELAY_ACTIVE_LOW ? LOW : HIGH) : (RELAY_ACTIVE_LOW ? HIGH : LOW);
  digitalWrite(pin, state);
}

void setCoinPulsePin(bool active) {
  int state = active ? (COIN_PULSE_ACTIVE_LOW ? LOW : HIGH) : (COIN_PULSE_ACTIVE_LOW ? HIGH : LOW);
  digitalWrite(PIN_COIN_PULSE_OUT, state);
}

// ==============================================================================
// 6. QR CODE DRAWING ENGINE (ON ILI9488 TFT LCD)
// ==============================================================================

// Zero-Failure Embedded GTECH Standee QR Matrix (Version 6, 41x41 modules)
// Payload: upi://pay?am=2.00&cu=INR&mc=5300&mode=19&pa=gtech282722.rzp@rxairtel&tn=Payment%20To%20GTECH&tr=qr_TuXKipEEX2KteF
const uint8_t STANDEE_QR_SIZE = 41;
const uint8_t PROGMEM STANDEE_QR_BITMAP[] = {
    0xFE, 0xD2, 0xBF, 0xE3, 0xBF, 0x80,
    0x82, 0x4A, 0x45, 0x88, 0xA0, 0x80,
    0xBA, 0xB7, 0xA2, 0xE0, 0xAE, 0x80,
    0xBA, 0xD0, 0x27, 0x2E, 0xAE, 0x80,
    0xBA, 0xE0, 0xA0, 0x17, 0xAE, 0x80,
    0x82, 0x6D, 0x82, 0x6D, 0xA0, 0x80,
    0xFE, 0xAA, 0xAA, 0xAA, 0xBF, 0x80,
    0x00, 0x43, 0xD3, 0x16, 0x00, 0x00,
    0xF2, 0xAF, 0x47, 0x87, 0x4E, 0x80,
    0x05, 0xA4, 0xDB, 0xA1, 0x7B, 0x80,
    0x5A, 0x4C, 0x25, 0x8C, 0xEF, 0x00,
    0x84, 0x69, 0xD8, 0xD9, 0x1C, 0x80,
    0xCB, 0x73, 0x82, 0x78, 0x06, 0x00,
    0xD4, 0x32, 0x4F, 0x9D, 0xE4, 0x80,
    0x2E, 0x2C, 0x52, 0x8B, 0xB7, 0x80,
    0x01, 0x69, 0x36, 0x39, 0x99, 0x00,
    0x5B, 0xB4, 0x8D, 0x61, 0x4C, 0x00,
    0x95, 0x9F, 0x2B, 0xF2, 0x07, 0x00,
    0x1F, 0xE9, 0x26, 0xBC, 0x1A, 0x00,
    0x98, 0xB9, 0xE1, 0x8E, 0x9A, 0x80,
    0xEE, 0xE5, 0x9C, 0x73, 0x2F, 0x80,
    0xA0, 0x43, 0xD4, 0x2D, 0xFE, 0x80,
    0x2F, 0x67, 0x4F, 0xA6, 0xE7, 0x00,
    0x50, 0x3D, 0x0A, 0xD3, 0xF9, 0x80,
    0x23, 0x16, 0x6A, 0xD0, 0xD4, 0x00,
    0x3D, 0x8D, 0x32, 0xDD, 0xE4, 0x80,
    0xAE, 0x42, 0xF8, 0xCB, 0x72, 0x80,
    0x68, 0x1C, 0x7F, 0x0B, 0x89, 0x00,
    0xBA, 0xB8, 0xE2, 0x07, 0x19, 0x80,
    0x0D, 0x40, 0x8A, 0xDD, 0xD5, 0x00,
    0x92, 0x81, 0xE4, 0x92, 0x38, 0x00,
    0x08, 0x52, 0x59, 0x26, 0xDE, 0x80,
    0x4B, 0xCA, 0x54, 0x1B, 0xFE, 0x80,
    0x00, 0xB0, 0x1D, 0x42, 0x8F, 0x80,
    0xFE, 0x1A, 0x47, 0xE7, 0xAD, 0x00,
    0x82, 0x47, 0xBA, 0xFB, 0x89, 0x80,
    0xBA, 0x79, 0x3B, 0x70, 0xFE, 0x00,
    0xBA, 0xF8, 0xF2, 0xA8, 0x1B, 0x80,
    0xBA, 0xF5, 0xFA, 0xA7, 0x51, 0x80,
    0x82, 0x92, 0x86, 0x83, 0xCD, 0x00,
    0xFE, 0xE5, 0x84, 0x4E, 0xB5, 0x00
};

/**
 * Draws the embedded Standee QR matrix pixel-perfectly on TFT LCD.
 * 100% reliable, zero-latency, scans immediately on all UPI apps!
 */
void drawStandeeBitmapQR(int startX, int startY, int maxBoxSize) {
  Serial.println("[LCD Screen] Rendering Embedded GTECH Standee QR Bitmap (Zero-Failure Preset)...");
  int scale = maxBoxSize / STANDEE_QR_SIZE; // 190 / 41 = 4
  int qrPxSize = STANDEE_QR_SIZE * scale;    // 41 * 4 = 164
  int border = (maxBoxSize - qrPxSize) / 2;  // 13
  int outerBox = qrPxSize + (border * 2);

  // Draw crisp white background card
  TFT_display.fillRect(startX, startY, outerBox, outerBox, COLOR_WHITE);
  TFT_display.drawRect(startX, startY, outerBox, outerBox, COLOR_BLUE);

  int bytesPerRow = (STANDEE_QR_SIZE + 7) / 8; // 6 bytes
  for (int y = 0; y < STANDEE_QR_SIZE; y++) {
    for (int x = 0; x < STANDEE_QR_SIZE; x++) {
      int byteIdx = y * bytesPerRow + (x / 8);
      int bitIdx = 7 - (x % 8);
      uint8_t byteVal = pgm_read_byte(&STANDEE_QR_BITMAP[byteIdx]);
      if (byteVal & (1 << bitIdx)) {
        TFT_display.fillRect(startX + border + (x * scale),
                             startY + border + (y * scale),
                             scale, scale, COLOR_BLACK);
      }
    }
  }
}

/**
 * Universal Dynamic QR Code Drawing Engine.
 * Supports UPI URIs (upi://) and Web Payment Links (http://, https://).
 * Dynamically selects smallest QR Version (1 to 10) with exact capacity guard.
 * Gracefully falls back to Standee Bitmap if string cannot fit.
 */
void drawQRCode(const char* text, int startX, int startY, int maxBoxSize) {
#if USE_CUSTOM_STATIC_BITMAP
  Serial.println("[LCD Screen] Rendering Raw Static QR Bitmap matrix (Bypassing dynamic encoder)...");
  drawStandeeBitmapQR(startX, startY, maxBoxSize);
  return;
#endif

  if (text == NULL || strlen(text) == 0 || strcmp(text, STATIC_QR_CODE) == 0) {
    drawStandeeBitmapQR(startX, startY, maxBoxSize);
    return;
  }

  Serial.printf("[LCD Screen] Generating QR code (%d chars): %s\n", (int)strlen(text), text);
  QRCode qrcode;
  uint8_t qrcodeBytes[qrcode_getBufferSize(10)];

  // Automatically find the smallest QR version (1 to 10) that fits payload
  int version = -1;
  for (int v = 1; v <= 10; v++) {
    int8_t res = qrcode_initText(&qrcode, qrcodeBytes, v, ECC_LOW, text);
    if (res == 0) {
      version = v;
      break;
    }
  }

  if (version < 0) {
    Serial.println("[QR Warning] String could not be dynamically encoded. Using embedded Standee Bitmap!");
    drawStandeeBitmapQR(startX, startY, maxBoxSize);
    return;
  }

  int scale = maxBoxSize / qrcode.size;
  if (scale < 2) scale = 2;

  int qrPxSize = qrcode.size * scale;
  int border = (maxBoxSize - qrPxSize) / 2;
  if (border < 4) border = 4;
  int outerBox = qrPxSize + (border * 2);

  // Draw crisp white background card
  TFT_display.fillRect(startX, startY, outerBox, outerBox, COLOR_WHITE);
  TFT_display.drawRect(startX, startY, outerBox, outerBox, COLOR_BLUE);

  // Render dark modules
  for (uint8_t y = 0; y < qrcode.size; y++) {
    for (uint8_t x = 0; x < qrcode.size; x++) {
      if (qrcode_getModule(&qrcode, x, y)) {
        TFT_display.fillRect(startX + border + (x * scale),
                             startY + border + (y * scale),
                             scale, scale, COLOR_BLACK);
      }
    }
  }
}

// ==============================================================================
// 7. USER INTERFACE (ILI9488 TFT LCD - ZERO-BUTTON STANDBY & DISPENSE SCREENS)
// ==============================================================================

/**
 * Live Dynamic Network & Internet Status Monitor
 * Instantly updates the LCD status badge and alert banner without redrawing or flickering the QR code!
 */
/**
 * Offline / No Internet Notice Panel (Replaces QR Code when disconnected)
 * Prevents customers from paying when machine cannot communicate with the cloud!
 * Displays prominent disconnected icon / symbol and clear warning text.
 */
/**
 * Out of Stock Notice Screen (Shown when stock_management_enabled == true && current_stock <= 0)
 * Completely hides QR code to prevent payments when machine is empty!
 */
void uiDrawOutOfStockNotice() {
  // Center Alert Box (x: 20, y: 144, w: 280, h: 236)
  TFT_display.fillRect(20, 144, 280, 236, COLOR_CARD);
  TFT_display.drawRect(20, 144, 280, 236, COLOR_RED);
  TFT_display.drawRect(21, 145, 278, 234, COLOR_RED);
  TFT_display.drawRect(23, 147, 274, 230, COLOR_CARD_BORDER);

  int cx = 160;
  int cy = 188;

  // Draw Big Red Circular 'Sold Out' Icon
  TFT_display.drawCircle(cx, cy, 26, COLOR_RED);
  TFT_display.drawCircle(cx, cy, 27, COLOR_RED);
  TFT_display.drawLine(cx - 18, cy - 18, cx + 18, cy + 18, COLOR_RED);
  TFT_display.drawLine(cx - 18, cy - 17, cx + 18, cy + 19, COLOR_RED);

  // Text inside Card
  TFT_display.setTextSize(2);
  TFT_display.setTextColor(COLOR_RED);
  TFT_display.setCursor(85, 230);
  TFT_display.print("OUT OF STOCK");

  TFT_display.setTextSize(1);
  TFT_display.setTextColor(COLOR_YELLOW);
  TFT_display.setCursor(75, 258);
  TFT_display.print("ALL MATERIAL DISPENSED");

  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setCursor(68, 276);
  TFT_display.print("QR PAYMENTS DISABLED");

  // Operator Refill Hint at bottom of box
  TFT_display.fillRect(35, 305, 250, 48, COLOR_DARK_GRAY);
  TFT_display.drawRect(35, 305, 250, 48, COLOR_CYAN);
  TFT_display.setCursor(45, 312);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(1);
  TFT_display.print("OPERATOR REFILL GUIDE:");
  TFT_display.setCursor(45, 326);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.print("Press SW 1 (GPIO 32) to set stock");
  TFT_display.setCursor(45, 338);
  TFT_display.setTextColor(COLOR_GREEN);
  TFT_display.print("Press SW 2 (GPIO 33) to save");
}

/**
 * Screen: Interactive On-Screen Stock Refill Menu
 * Triggered by pressing Push Switch 1 (GPIO 32).
 * Cycles 1 to 50, then wraps to 1!
 */
void uiDrawStockRefillScreen(int count) {
  TFT_display.fillScreen(COLOR_BG);

  // Top Header Bar (Emerald / Cyan)
  TFT_display.fillRect(0, 0, 320, 48, COLOR_HEADER);
  TFT_display.drawFastHLine(0, 48, 320, COLOR_CYAN);
  TFT_display.setCursor(15, 14);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(2);
  TFT_display.print("STOCK REFILL MENU");

  // Machine ID badge
  TFT_display.setCursor(15, 58);
  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.setTextSize(1);
  TFT_display.printf("Machine ID: [%s] | Active Stock: %d", device_id.c_str(), current_stock);

  // Main Card Box (y: 78 - 315, h: 237)
  TFT_display.fillRect(15, 78, 290, 237, COLOR_CARD);
  TFT_display.drawRect(15, 78, 290, 237, COLOR_CYAN);

  TFT_display.setCursor(30, 95);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  TFT_display.print("SET NEW STOCK:");

  // Number Display Box (y: 130 - 215)
  TFT_display.fillRect(35, 126, 250, 84, COLOR_HEADER);
  TFT_display.drawRect(35, 126, 250, 84, COLOR_GREEN);

  // Centered Large Number
  TFT_display.setTextColor(COLOR_YELLOW);
  TFT_display.setTextSize(5);
  if (count < 10) {
    TFT_display.setCursor(110, 142);
  } else {
    TFT_display.setCursor(85, 142);
  }
  TFT_display.printf("%d", count);

  TFT_display.setCursor(170, 162);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(2);
  TFT_display.print("UNITS");

  // Visual Stock Gauge (1 to 50)
  TFT_display.drawRect(35, 226, 250, 20, COLOR_WHITE);
  int fillW = (count * 246) / MAX_SELECTABLE_STOCK;
  if (fillW > 246) fillW = 246;
  TFT_display.fillRect(37, 228, fillW, 16, COLOR_GREEN);

  TFT_display.setCursor(35, 254);
  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.setTextSize(1);
  TFT_display.print("Min: 1");
  TFT_display.setCursor(140, 254);
  TFT_display.print("25");
  TFT_display.setCursor(235, 254);
  TFT_display.print("Max: 50");

  TFT_display.setCursor(30, 280);
  TFT_display.setTextColor(COLOR_AMBER);
  TFT_display.setTextSize(1);
  TFT_display.print("Count cycles 1 -> 50, then restarts at 1");

  // Bottom Instructions Card (y: 325 - 468, h: 143)
  TFT_display.fillRect(15, 325, 290, 143, COLOR_DARK_GRAY);
  TFT_display.drawRect(15, 325, 290, 143, COLOR_CARD_BORDER);

  TFT_display.setCursor(25, 338);
  TFT_display.setTextColor(COLOR_AMBER);
  TFT_display.setTextSize(1);
  TFT_display.print("HARDWARE PUSH BUTTON CONTROLS:");

  TFT_display.setCursor(25, 358);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.print("🔘 SW 1 (GPIO 32): Update Stock (+1)");

  TFT_display.setCursor(25, 378);
  TFT_display.setTextColor(COLOR_GREEN);
  TFT_display.print("💾 SW 2 (GPIO 33): SELECT & SAVE STOCK");

  TFT_display.setCursor(25, 402);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.print("🌐 Web Portal / SW2 (4s): Mode Toggle");

  TFT_display.setCursor(25, 424);
  TFT_display.setTextColor(COLOR_YELLOW);
  TFT_display.print("📶 Hold BOOT (3s): Open Wi-Fi Hotspot");

  TFT_display.setCursor(25, 446);
  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.print("Auto-exits to QR screen in 25s if idle");
}

/**
 * Screen: Stock Saved Confirmation
 */
void uiDrawStockSavedScreen(int count) {
  TFT_display.fillScreen(COLOR_BG);

  TFT_display.fillRect(0, 0, 320, 50, COLOR_GREEN);
  TFT_display.setCursor(20, 14);
  TFT_display.setTextColor(COLOR_BLACK);
  TFT_display.setTextSize(2);
  TFT_display.print("STOCK UPDATED!");

  TFT_display.fillRect(15, 70, 290, 380, COLOR_CARD);
  TFT_display.drawRect(15, 70, 290, 380, COLOR_GREEN);

  TFT_display.fillRect(25, 110, 270, 100, COLOR_HEADER);
  TFT_display.drawRect(25, 110, 270, 100, COLOR_GREEN);

  TFT_display.setCursor(45, 126);
  TFT_display.setTextColor(COLOR_GREEN);
  TFT_display.setTextSize(2);
  TFT_display.print("NEW INVENTORY:");

  TFT_display.setCursor(75, 160);
  TFT_display.setTextColor(COLOR_YELLOW);
  TFT_display.setTextSize(3);
  TFT_display.printf("%d UNITS", count);

  TFT_display.setCursor(30, 240);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  TFT_display.print("Saved to Flash NVS");

  TFT_display.setCursor(30, 275);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(1);
  TFT_display.print("Machine inventory successfully synced.");

  TFT_display.setCursor(30, 305);
  TFT_display.setTextColor(COLOR_AMBER);
  TFT_display.setTextSize(1);
  TFT_display.print("Reporting new stock level to AWS Cloud...");

  TFT_display.setCursor(30, 350);
  TFT_display.setTextColor(COLOR_GREEN);
  TFT_display.setTextSize(2);
  TFT_display.print("READY TO VEND!");
}

/**
 * Screen: Stock Management Mode Toggled (Stock-Based vs Without Stock)
 */
void uiDrawModeToggledScreen(bool stockModeOn) {
  TFT_display.fillScreen(COLOR_BG);

  uint16_t headerCol = stockModeOn ? COLOR_GREEN : COLOR_AMBER;
  TFT_display.fillRect(0, 0, 320, 50, headerCol);
  TFT_display.setCursor(20, 14);
  TFT_display.setTextColor(COLOR_BLACK);
  TFT_display.setTextSize(2);
  TFT_display.print("MACHINE MODE CHANGED");

  TFT_display.fillRect(15, 70, 290, 380, COLOR_CARD);
  TFT_display.drawRect(15, 70, 290, 380, headerCol);

  TFT_display.setCursor(30, 105);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  TFT_display.print("Current Mode:");

  TFT_display.fillRect(25, 145, 270, 90, COLOR_HEADER);
  TFT_display.drawRect(25, 145, 270, 90, headerCol);

  if (stockModeOn) {
    TFT_display.setCursor(40, 160);
    TFT_display.setTextColor(COLOR_GREEN);
    TFT_display.setTextSize(2);
    TFT_display.print("STOCK-BASED MODE");

    TFT_display.setCursor(40, 192);
    TFT_display.setTextColor(COLOR_CYAN);
    TFT_display.setTextSize(2);
    TFT_display.printf("Active Stock: %d", current_stock);

    TFT_display.setCursor(30, 260);
    TFT_display.setTextColor(COLOR_WHITE);
    TFT_display.setTextSize(1);
    TFT_display.print("Machine tracks stock and stops when empty.");
  } else {
    TFT_display.setCursor(40, 160);
    TFT_display.setTextColor(COLOR_YELLOW);
    TFT_display.setTextSize(2);
    TFT_display.print("WITHOUT-STOCK MODE");

    TFT_display.setCursor(40, 192);
    TFT_display.setTextColor(COLOR_WHITE);
    TFT_display.setTextSize(2);
    TFT_display.print("Unlimited Vending");

    TFT_display.setCursor(30, 260);
    TFT_display.setTextColor(COLOR_WHITE);
    TFT_display.setTextSize(1);
    TFT_display.print("Continuous continuous vending with no stock limit.");
  }

  TFT_display.setCursor(30, 300);
  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.setTextSize(1);
  TFT_display.print("Hold SW 2 (4s) anytime to toggle mode.");

  TFT_display.setCursor(30, 350);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(2);
  TFT_display.print("Returning to Standby...");
}

void uiDrawOfflineNotice(NetworkStatus status) {
  bool isNoWifi = (status == NET_STATUS_NO_WIFI);
  uint16_t accentColor = isNoWifi ? COLOR_RED : COLOR_AMBER;

  // 1. Draw Offline Card Box centered (x: 20, y: 144, w: 280, h: 236)
  TFT_display.fillRect(20, 144, 280, 236, COLOR_CARD);
  TFT_display.drawRect(20, 144, 280, 236, accentColor);
  TFT_display.drawRect(21, 145, 278, 234, accentColor);
  TFT_display.drawRect(23, 147, 274, 230, COLOR_CARD_BORDER);

  int cx = 160; // Horizontal center of vertical 320px screen

  if (isNoWifi) {
    // --- ICON: WI-FI DISCONNECTED SYMBOL ---
    int cy = 188;

    // Wi-Fi base dot
    TFT_display.fillCircle(cx, cy + 18, 4, COLOR_GRAY);

    // Wi-Fi outer wave arcs
    TFT_display.drawCircle(cx, cy + 18, 16, COLOR_GRAY);
    TFT_display.drawCircle(cx, cy + 18, 17, COLOR_GRAY);
    TFT_display.drawCircle(cx, cy + 18, 28, COLOR_GRAY);
    TFT_display.drawCircle(cx, cy + 18, 29, COLOR_GRAY);

    // Mask bottom half so only upper arcs appear
    TFT_display.fillRect(25, cy + 19, 270, 35, COLOR_CARD);

    // Bold Red 'X' across the Wi-Fi icon
    for (int o = -2; o <= 2; o++) {
      TFT_display.drawLine(cx - 26 + o, cy - 8, cx + 26 + o, cy + 26, COLOR_RED);
      TFT_display.drawLine(cx + 26 + o, cy - 8, cx - 26 + o, cy + 26, COLOR_RED);
    }

    // Title: NO WI-FI
    TFT_display.setTextSize(2);
    TFT_display.setTextColor(COLOR_RED);
    TFT_display.setCursor(110, 235);
    TFT_display.print("NO WI-FI");
  } else {
    // --- ICON: WARNING TRIANGLE SYMBOL ---
    int cy = 186;

    // Bold layered warning triangle
    for (int t = 0; t < 3; t++) {
      TFT_display.drawTriangle(cx, cy - 26 + t, cx - 30 + t, cy + 18 - t, cx + 30 - t, cy + 18 - t, COLOR_AMBER);
    }
    TFT_display.drawTriangle(cx, cy - 24, cx - 28, cy + 16, cx + 28, cy + 16, COLOR_YELLOW);

    // Exclamation Mark '!'
    TFT_display.fillRect(cx - 2, cy - 14, 5, 18, COLOR_WHITE);
    TFT_display.fillCircle(cx, cy + 12, 2, COLOR_WHITE);

    // Title: NO INTERNET
    TFT_display.setTextSize(2);
    TFT_display.setTextColor(COLOR_AMBER);
    TFT_display.setCursor(92, 235);
    TFT_display.print("NO INTERNET");
  }

  // Subtext inside box
  TFT_display.setTextSize(1);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setCursor(85, 266);
  TFT_display.print("QR PAYMENTS OFFLINE");

  TFT_display.setTextColor(COLOR_YELLOW);
  TFT_display.setCursor(88, 284);
  TFT_display.print("PLEASE DO NOT PAY");

  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.setCursor(105, 304);
  TFT_display.print("Reconnecting...");

  // Status pill at bottom of box
  TFT_display.fillRect(35, 332, 250, 24, COLOR_DARK_GRAY);
  TFT_display.drawRect(35, 332, 250, 24, COLOR_CARD_BORDER);
  TFT_display.setCursor(isNoWifi ? 95 : 85, 338);
  TFT_display.setTextColor(accentColor);
  TFT_display.setTextSize(1);
  TFT_display.print(isNoWifi ? "WiFi Signal Lost" : "Cloud Link Offline");
}

/**
 * Live Dynamic Network & Internet Status Monitor
 * Automatically hides/shows the QR code based on cloud and WiFi status!
 */
void uiUpdateNetworkStatus(NetworkStatus newStatus) {
  if (current_state != STATE_STANDBY_QR) return;
  if (stock_management_enabled && current_stock <= 0) return;
  if (newStatus == current_net_status) return;

  NetworkStatus oldStatus = current_net_status;
  current_net_status = newStatus;

  Serial.printf("[Net Status] State change: %d -> %d\n", oldStatus, newStatus);

  // Whenever network transitions between ONLINE and OFFLINE (or between NO_WIFI and NO_INTERNET),
  // re-render the screen so the QR code is immediately hidden (offline) or restored (online)!
  uiDrawStandbyQRScreen();
}

/**
 * Screen 1: Permanent Standby QR Screen
 * Customer simply scans the QR code on screen and pays ₹10. No buttons needed!
 */
void uiDrawStandbyQRScreen() {
  TFT_display.fillScreen(COLOR_BG);

  // 1. Top Header Bar (y: 0 - 45, width: 320)
  TFT_display.fillRect(0, 0, 320, 45, COLOR_HEADER);
  TFT_display.drawFastHLine(0, 45, 320, COLOR_BLUE);

  TFT_display.setCursor(12, 14);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  TFT_display.print("SMART VEND");

  // Status Badge on Header (Right-Aligned)
  if (WiFi.status() != WL_CONNECTED) {
    current_net_status = NET_STATUS_NO_WIFI;
    TFT_display.setCursor(185, 14);
    TFT_display.setTextColor(COLOR_RED);
    TFT_display.setTextSize(2);
    TFT_display.print("NO WI-FI");
  } else if (current_net_status == NET_STATUS_NO_INTERNET) {
    TFT_display.setCursor(175, 14);
    TFT_display.setTextColor(COLOR_AMBER);
    TFT_display.setTextSize(2);
    TFT_display.print("NO CLOUD");
  } else if (stock_management_enabled && current_stock <= 0) {
    TFT_display.setCursor(175, 14);
    TFT_display.setTextColor(COLOR_RED);
    TFT_display.setTextSize(2);
    TFT_display.print("EMPTY");
  } else {
    current_net_status = NET_STATUS_ONLINE;
    if (payment_mode.equalsIgnoreCase("COIN_ONLY")) {
      TFT_display.setCursor(175, 14);
      TFT_display.setTextColor(COLOR_YELLOW);
      TFT_display.setTextSize(2);
      TFT_display.print("COIN ONLY");
    } else if (payment_mode.equalsIgnoreCase("QR_ONLY")) {
      TFT_display.setCursor(185, 14);
      TFT_display.setTextColor(COLOR_CYAN);
      TFT_display.setTextSize(2);
      TFT_display.print("QR ONLY");
    } else {
      TFT_display.setCursor(175, 14);
      TFT_display.setTextColor(COLOR_GREEN);
      TFT_display.setTextSize(2);
      TFT_display.print("QR + COIN");
    }
  }

  // 2. Product & Price Card (y: 52 - 138, width: 300, height: 86)
  TFT_display.fillRect(10, 52, 300, 86, COLOR_CARD);
  TFT_display.drawRect(10, 52, 300, 86, COLOR_CARD_BORDER);

  // Product Badge & Stock / Machine Indicator
  TFT_display.fillRect(18, 58, 85, 20, COLOR_BLUE);
  TFT_display.setCursor(22, 62);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(1);
  TFT_display.print("PRODUCT 1");

  // Stock Badge: Displays real-time stock when in Stock-Based mode!
  if (stock_management_enabled) {
    uint16_t stockBadgeCol = (current_stock > 5) ? COLOR_GREEN : (current_stock > 0 ? COLOR_AMBER : COLOR_RED);
    TFT_display.fillRect(110, 58, 95, 20, COLOR_DARK_GRAY);
    TFT_display.drawRect(110, 58, 95, 20, stockBadgeCol);
    TFT_display.setCursor(115, 62);
    TFT_display.setTextColor(stockBadgeCol);
    TFT_display.setTextSize(1);
    if (current_stock > 0) {
      TFT_display.printf("STOCK: %d", current_stock);
    } else {
      TFT_display.print("EMPTY: 0");
    }
  } else {
    TFT_display.fillRect(110, 58, 95, 20, COLOR_DARK_GRAY);
    TFT_display.drawRect(110, 58, 95, 20, COLOR_CYAN);
    TFT_display.setCursor(115, 62);
    TFT_display.setTextColor(COLOR_CYAN);
    TFT_display.setTextSize(1);
    TFT_display.print("UNLIMITED");
  }

  TFT_display.setCursor(215, 62);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(2);
  TFT_display.printf("[%s]", device_id.c_str());

  // Product Title
  TFT_display.setCursor(18, 86);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  String pName = pending_product_name;
  if (pName.length() > 18) pName = pName.substring(0, 16) + "..";
  TFT_display.print(pName.c_str());

  // Price Display
  TFT_display.setCursor(18, 110);
  TFT_display.setTextColor(COLOR_GREEN);
  TFT_display.setTextSize(3);
  TFT_display.printf("Rs %.2f", pending_amount_rupee);

  // Construct Dynamic or Static Razorpay UPI Payload or Custom Payment URL
#if FORCE_STATIC_PROGRAM_CONFIG
  String upiUri = String(STATIC_QR_CODE);
  pending_product_name = String(STATIC_PRODUCT_NAME);
  pending_amount_rupee = STATIC_PRICE_RUPEES;
#else
  String upiUri = (custom_qr_code.length() > 0) ? custom_qr_code : 
                  ("upi://pay?pa=" + razorpay_upi_vpa + 
                  "&pn=IoT%20Vending&am=" + String(pending_amount_rupee, 2) + 
                  "&cu=INR&tn=" + device_id);
#endif

  // Guard against raw image data URIs or oversized blobs
  if (upiUri.startsWith("data:") || upiUri.length() > 250) {
    upiUri = "upi://pay?pa=" + razorpay_upi_vpa + 
             "&pn=IoT%20Vending&am=" + String(pending_amount_rupee, 2) + 
             "&cu=INR&tn=" + device_id;
  }

  // 3. Middle Section: QR Code, Coin Acceptor Card, Out of Stock, or Offline Warning
  if (stock_management_enabled && current_stock <= 0) {
    // Machine is empty! Hide QR and show Out of Stock Alert
    uiDrawOutOfStockNotice();
  } else if (payment_mode.equalsIgnoreCase("COIN_ONLY")) {
    // Dedicated Coin Acceptor Screen (no QR displayed)
    TFT_display.fillRect(20, 148, 280, 226, COLOR_CARD);
    TFT_display.drawRect(20, 148, 280, 226, COLOR_AMBER);

    // Coin Graphic Circle
    TFT_display.fillCircle(160, 215, 45, COLOR_HEADER);
    TFT_display.drawCircle(160, 215, 45, COLOR_YELLOW);
    TFT_display.drawCircle(160, 215, 43, COLOR_AMBER);
    TFT_display.setTextColor(COLOR_YELLOW);
    TFT_display.setTextSize(4);
    TFT_display.setCursor(140, 202);
    TFT_display.print("Rs");

    TFT_display.setCursor(35, 275);
    TFT_display.setTextColor(COLOR_WHITE);
    TFT_display.setTextSize(2);
    TFT_display.print("INSERT COIN TO VEND");

    TFT_display.setCursor(55, 305);
    TFT_display.setTextColor(COLOR_GREEN);
    TFT_display.setTextSize(2);
    TFT_display.printf("Price: Rs %.2f", pending_amount_rupee);

    TFT_display.setCursor(45, 338);
    TFT_display.setTextColor(COLOR_CYAN);
    TFT_display.setTextSize(1);
    TFT_display.print("Coin Acceptor Active (GPIO 13 -> 25)");

    TFT_display.setCursor(65, 355);
    TFT_display.setTextColor(COLOR_GRAY);
    TFT_display.setTextSize(1);
    TFT_display.print("Accepts Rs 1, Rs 2 & Rs 5 Coins");
  } else if (current_net_status == NET_STATUS_ONLINE) {
    // Draw 190x190 Razorpay QR Code perfectly centered in 320px width: (320 - 190)/2 = 65
    drawQRCode(upiUri.c_str(), 65, 144, 190);

    // Subtext under QR
    if (payment_mode.equalsIgnoreCase("BOTH")) {
      TFT_display.setCursor(30, 342);
      TFT_display.setTextColor(COLOR_YELLOW);
      TFT_display.setTextSize(1);
      TFT_display.print("OR INSERT PHYSICAL COIN IN SLOT");

      TFT_display.setCursor(45, 358);
      TFT_display.setTextColor(COLOR_WHITE);
      TFT_display.setTextSize(1);
      TFT_display.print("Scan UPI QR OR Drop Coin to Vend");
    } else {
      TFT_display.setCursor(45, 342);
      TFT_display.setTextColor(COLOR_WHITE);
      TFT_display.setTextSize(1);
      TFT_display.print("GPay / PhonePe / Paytm / BHIM");

      TFT_display.setCursor(70, 358);
      TFT_display.setTextColor(COLOR_CYAN);
      TFT_display.setTextSize(1);
      TFT_display.print("Powered by Razorpay Route");
    }

    TFT_display.setCursor(40, 372);
    TFT_display.setTextColor(COLOR_GRAY);
    TFT_display.setTextSize(1);
    TFT_display.print("Auto-Transfers to Vendor Account");
  } else {
    // Machine is offline: Draw centered alert notice
    uiDrawOfflineNotice(current_net_status);
  }

  // 4. Instructions & Live Status Footer Card (y: 388 - 472, height: 84)
  TFT_display.fillRect(10, 388, 300, 84, COLOR_DARK_GRAY);
  TFT_display.drawRect(10, 388, 300, 84, COLOR_CARD_BORDER);

  if (stock_management_enabled && current_stock <= 0) {
    TFT_display.setCursor(18, 396);
    TFT_display.setTextColor(COLOR_RED);
    TFT_display.setTextSize(1);
    TFT_display.print("MACHINE TEMPORARILY OUT OF STOCK");

    TFT_display.setCursor(18, 410);
    TFT_display.setTextColor(COLOR_WHITE);
    TFT_display.setTextSize(1);
    TFT_display.print("Please contact operator to refill items.");

    TFT_display.setCursor(18, 424);
    TFT_display.setTextColor(COLOR_CYAN);
    TFT_display.setTextSize(1);
    TFT_display.print("Operator: Press SW 1 (GPIO 32) to refill");

    TFT_display.setCursor(18, 444);
    TFT_display.setTextColor(COLOR_GRAY);
    TFT_display.setTextSize(1);
    TFT_display.print("STATUS: ");
    TFT_display.setTextColor(COLOR_RED);
    TFT_display.setTextSize(2);
    TFT_display.print("EMPTY (NO VEND)");
  } else if (payment_mode.equalsIgnoreCase("COIN_ONLY")) {
    TFT_display.setCursor(18, 396);
    TFT_display.setTextColor(COLOR_YELLOW);
    TFT_display.setTextSize(1);
    TFT_display.print("COIN VENDING ACTIVE - INSERT COIN");

    TFT_display.setCursor(18, 410);
    TFT_display.setTextColor(COLOR_WHITE);
    TFT_display.setTextSize(1);
    TFT_display.printf("Insert coin into acceptor -> Motor auto-dispenses");

    TFT_display.setCursor(18, 424);
    TFT_display.setTextColor(COLOR_CYAN);
    TFT_display.setTextSize(1);
    TFT_display.print("Pulse mirrored to coin pulse out (GPIO 25)");

    TFT_display.setCursor(18, 444);
    TFT_display.setTextColor(COLOR_GRAY);
    TFT_display.setTextSize(1);
    TFT_display.print("STATUS: ");
    TFT_display.setTextColor(COLOR_YELLOW);
    TFT_display.setTextSize(2);
    TFT_display.print("COIN READY");
  } else if (payment_mode.equalsIgnoreCase("BOTH")) {
    TFT_display.setCursor(18, 396);
    TFT_display.setTextColor(COLOR_GREEN);
    TFT_display.setTextSize(1);
    TFT_display.print("HYBRID: UPI QR OR PHYSICAL COIN");

    TFT_display.setCursor(18, 410);
    TFT_display.setTextColor(COLOR_WHITE);
    TFT_display.setTextSize(1);
    TFT_display.printf("Scan QR to Pay OR Drop Coin in Acceptor");

    TFT_display.setCursor(18, 424);
    TFT_display.setTextColor(COLOR_CYAN);
    TFT_display.setTextSize(1);
    TFT_display.print("Coin pulses mirrored to Out (GPIO 25)");

    TFT_display.setCursor(18, 444);
    TFT_display.setTextColor(COLOR_GRAY);
    TFT_display.setTextSize(1);
    TFT_display.print("STATUS: ");
    TFT_display.setTextColor(COLOR_GREEN);
    TFT_display.setTextSize(2);
    TFT_display.print("QR + COIN READY");
  } else if (current_net_status == NET_STATUS_ONLINE) {
    TFT_display.setCursor(18, 396);
    TFT_display.setTextColor(COLOR_CYAN);
    TFT_display.setTextSize(1);
    TFT_display.print("ZERO-TOUCH DISPENSE ACTIVE (NO BUTTONS)");

    TFT_display.setCursor(18, 410);
    TFT_display.setTextColor(COLOR_WHITE);
    TFT_display.setTextSize(1);
    TFT_display.printf("1. Scan QR   2. Pay Rs %.2f   3. Auto-Vends", pending_amount_rupee);

    TFT_display.setCursor(18, 424);
    TFT_display.setTextColor(COLOR_GRAY);
    TFT_display.setTextSize(1);
    TFT_display.print("Automatic dispense on verified payment");

    TFT_display.setCursor(18, 444);
    TFT_display.setTextColor(COLOR_GRAY);
    TFT_display.setTextSize(1);
    TFT_display.print("STATUS: ");
    TFT_display.setTextColor(COLOR_CYAN);
    TFT_display.setTextSize(2);
    TFT_display.print("QR READY");
  } else {
    TFT_display.setCursor(18, 396);
    TFT_display.setTextColor(COLOR_RED);
    TFT_display.setTextSize(1);
    TFT_display.print("VENDING TEMPORARILY OFFLINE");

    TFT_display.setCursor(18, 410);
    TFT_display.setTextColor(COLOR_WHITE);
    TFT_display.setTextSize(1);
    TFT_display.print("No internet link to verify payments");

    TFT_display.setCursor(18, 424);
    TFT_display.setTextColor(COLOR_AMBER);
    TFT_display.setTextSize(1);
    TFT_display.print("Please stand by for auto-reconnect");

    // Status Line
    TFT_display.setCursor(18, 444);
    TFT_display.setTextColor(COLOR_GRAY);
    TFT_display.setTextSize(1);
    TFT_display.print("STATUS: ");

    TFT_display.setTextColor(COLOR_RED);
    TFT_display.setTextSize(2);
    TFT_display.print("OFFLINE (NO PAY)");
  }
}

/**
 * Screen 2: Vending In Progress & "PLEASE COLLECT MATERIAL"
 * Displays PAYMENT SUCCESSFUL, amount, and product name on machine's ILI9488 TFT
 */
void uiDrawVendingScreen(int slotNumber, float amount, String productName) {
  TFT_display.fillScreen(COLOR_BG);

  // Top Banner (Emerald Green) - Requirement 9: PAYMENT SUCCESSFUL
  TFT_display.fillRect(0, 0, 320, 50, COLOR_GREEN);
  TFT_display.setCursor(18, 14);
  TFT_display.setTextColor(COLOR_BLACK);
  TFT_display.setTextSize(2);
  TFT_display.print("PAYMENT SUCCESSFUL!");

  // Main Card Box (y: 60 - 465, height: 405)
  TFT_display.fillRect(15, 60, 290, 405, COLOR_CARD);
  TFT_display.drawRect(15, 60, 290, 405, COLOR_CYAN);

  // Product Name & Amount details
  TFT_display.setCursor(25, 78);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  String displayName = (productName.length() > 0) ? productName : pending_product_name;
  if (displayName.length() > 16) displayName = displayName.substring(0, 14) + "..";
  TFT_display.printf("Item  : %s", displayName.c_str());

  TFT_display.setCursor(25, 108);
  TFT_display.setTextColor(COLOR_AMBER);
  TFT_display.setTextSize(2);
  TFT_display.printf("Amount: Rs. %.2f", amount);

  // Progress Bar Outer Frame (Width: 270)
  TFT_display.drawRect(25, 142, 270, 28, COLOR_WHITE);

  // Prominent "PLEASE COLLECT MATERIAL" Banner
  TFT_display.fillRect(25, 190, 270, 80, COLOR_GREEN);
  TFT_display.setCursor(45, 204);
  TFT_display.setTextColor(COLOR_BLACK);
  TFT_display.setTextSize(2);
  TFT_display.print("PLEASE COLLECT");

  TFT_display.setCursor(55, 236);
  TFT_display.setTextColor(COLOR_BLACK);
  TFT_display.setTextSize(3);
  TFT_display.print("MATERIAL");

  // Subtext
  TFT_display.setCursor(25, 295);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(2);
  TFT_display.printf("Dispensing Motor %d", slotNumber);

  TFT_display.setCursor(25, 335);
  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.setTextSize(1);
  TFT_display.print("Please wait while motor cycles...");

  TFT_display.setCursor(25, 365);
  TFT_display.setTextColor(COLOR_YELLOW);
  TFT_display.setTextSize(1);
  TFT_display.print("Item dropping into pickup tray below.");
}

/**
 * Screen 3: Vending Complete & Collect Material from Tray
 */
void uiDrawCompleteScreen() {
  TFT_display.fillScreen(COLOR_BG);

  // Top Green Header
  TFT_display.fillRect(0, 0, 320, 50, COLOR_GREEN);
  TFT_display.setCursor(20, 14);
  TFT_display.setTextColor(COLOR_BLACK);
  TFT_display.setTextSize(2);
  TFT_display.print("DISPENSE COMPLETED!");

  // Center Card (y: 65 - 460, height: 395)
  TFT_display.fillRect(15, 65, 290, 395, COLOR_CARD);
  TFT_display.drawRect(15, 65, 290, 395, COLOR_GREEN);

  // Big Prominent Highlight Box
  TFT_display.fillRect(25, 105, 270, 95, COLOR_GREEN);
  TFT_display.setCursor(45, 122);
  TFT_display.setTextColor(COLOR_BLACK);
  TFT_display.setTextSize(2);
  TFT_display.print("PLEASE COLLECT");

  TFT_display.setCursor(35, 156);
  TFT_display.setTextColor(COLOR_BLACK);
  TFT_display.setTextSize(3);
  TFT_display.print("YOUR ITEM");

  // Instruction Subtitle
  TFT_display.setCursor(25, 235);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(2);
  TFT_display.print("READY IN BOTTOM TRAY");

  TFT_display.setCursor(35, 290);
  TFT_display.setTextColor(COLOR_AMBER);
  TFT_display.setTextSize(2);
  TFT_display.print("THANK YOU! VISIT AGAIN");
}

// ==============================================================================
// 8. FLASH NVS PERSISTENCE HANDLERS
// ==============================================================================
void loadPersistentConfig() {
  prefs.begin("vending_cfg", false);
  String saved_ssid     = prefs.getString("ssid", "");
  String saved_pass     = prefs.getString("pass", "");
  String saved_url      = prefs.getString("srv_url", "");
  String saved_vpa      = prefs.getString("rzp_vpa", "");
  String saved_qr       = prefs.getString("cust_qr", "");
  String last_code_ssid = prefs.getString("code_ssid", "");
  bool has_remote_wifi  = prefs.getBool("wifi_remote", false);

  // --- SMART WI-FI SELECTION ---
  // 1. If user configured Wi-Fi via Cloud Web Portal or Captive Portal, always honor it:
  if (has_remote_wifi && saved_ssid.length() > 0) {
    wifi_ssid = saved_ssid;
    wifi_pass = saved_pass;
    Serial.printf("[Config] 📶 Cloud/Saved Wi-Fi active: %s\n", wifi_ssid.c_str());
  } else if (wifi_ssid.length() > 0 && wifi_ssid != last_code_ssid) {
    // 2. If the developer changed wifi_ssid in Arduino code:
    // wifi_ssid != last_code_ssid -> ALWAYS take precedence and save directly to Flash NVS!
    prefs.putString("ssid", wifi_ssid);
    prefs.putString("pass", wifi_pass);
    prefs.putString("code_ssid", wifi_ssid);
    Serial.printf("[Config] ⭐ New Wi-Fi from sketch code detected & applied: %s\n", wifi_ssid.c_str());
  } else if (saved_ssid.length() > 0) {
    // 3. Fallback to saved credentials
    wifi_ssid = saved_ssid;
    wifi_pass = saved_pass;
  }

  if (saved_url.length() > 0 && server_base_url == "http://35.154.219.82:8000") server_base_url = saved_url;
  if (saved_vpa.length() > 0 && razorpay_upi_vpa == "rzp.vending.vm000001@icici") razorpay_upi_vpa = saved_vpa;

#if FORCE_STATIC_PROGRAM_CONFIG
  // Enforce Static Program QR, Name, and Price from Arduino IDE code!
  custom_qr_code       = String(STATIC_QR_CODE);
  pending_product_name = String(STATIC_PRODUCT_NAME);
  pending_amount_rupee = STATIC_PRICE_RUPEES;

  // Persist to Flash NVS so it never reverts
  prefs.putString("cust_qr", custom_qr_code);
  prefs.putString("p_name", pending_product_name);
  prefs.putFloat("price", pending_amount_rupee);

  Serial.println("\n******************************************************************");
  Serial.println(">>> ⭐ STATIC PROGRAM CONFIG ENFORCED FROM ARDUINO CODE! <<<");
  Serial.printf("    Active Wi-Fi SSID: %s\n", wifi_ssid.c_str());
  Serial.printf("    Static QR String : %s\n", custom_qr_code.c_str());
  Serial.printf("    Product Name     : %s\n", pending_product_name.c_str());
  Serial.printf("    Price            : Rs %.2f\n", pending_amount_rupee);
  Serial.println("******************************************************************\n");
#else
  if (saved_qr.length() > 0) custom_qr_code = saved_qr;
  device_id = prefs.getString("dev_id", device_id);
  pending_amount_rupee = prefs.getFloat("price", pending_amount_rupee);
  pending_product_name = prefs.getString("p_name", pending_product_name);
  current_config_version = prefs.getInt("cfg_ver", current_config_version);
  dynamic_tr_id = prefs.getString("tr_id", "");
#endif
  last_dispensed_order_id = prefs.getString("last_order", "");
  
  // Load Stock Management state and quantity
  stock_management_enabled = prefs.getBool("stock_en", ENABLE_STOCK_MANAGEMENT);
  current_stock            = prefs.getInt("stock", DEFAULT_INITIAL_STOCK);
  payment_mode             = prefs.getString("pay_mode", "BOTH");
  refill_stock_count       = current_stock;
  prefs.end();

  Serial.println("\n==================================================================");
  Serial.println("  >>> ⚡ ESP32 RAZORPAY ZERO-BUTTON VENDING CONTROLLER <<<       ");
  Serial.println("==================================================================");
  Serial.printf("  Device ID (Machine)  : %s\n", device_id.c_str());
  Serial.printf("  Hardware MAC Address : %s\n", getDeviceMacAddress().c_str());
  Serial.printf("  Razorpay UPI VPA     : %s\n", razorpay_upi_vpa.c_str());
  Serial.printf("  Item Price (Rupees)  : Rs %.2f\n", pending_amount_rupee);
  Serial.printf("  Stock Management     : %s\n", stock_management_enabled ? "ENABLED (Stock-Based)" : "DISABLED (Continuous/Unlimited)");
  Serial.printf("  Current Stock Level  : %d / %d Units\n", current_stock, MAX_SELECTABLE_STOCK);
  Serial.printf("  Dispense Drop Sensor : GPIO %d (Active %s, %s)\n", PIN_DISPENSE_SENSOR, DISPENSE_SENSOR_ACTIVE_LOW ? "LOW" : "HIGH", DISPENSE_SENSOR_ENABLED ? "ENABLED" : "DISABLED");
  Serial.printf("  Coin Acceptor Input  : GPIO %d (Active %s, Mirrored to Out GPIO %d)\n", PIN_COIN_INPUT, COIN_INPUT_ACTIVE_LOW ? "LOW" : "HIGH", PIN_COIN_PULSE_OUT);
  Serial.printf("  Payment Mode (Web)   : %s (QR_ONLY, COIN_ONLY, BOTH)\n", payment_mode.c_str());
  Serial.printf("  Push Switch 1 (Cycle): GPIO %d (1 to 50)\n", PIN_STOCK_INC_BTN);
  Serial.printf("  Push Switch 2 (Save) : GPIO %d (NVS Flash Persistence)\n", PIN_STOCK_SAVE_BTN);
  Serial.printf("  Target Wi-Fi SSID    : %s\n", wifi_ssid.length() > 0 ? wifi_ssid.c_str() : "(Not Configured)");
  Serial.printf("  Cloud Server Base URL: %s\n", server_base_url.c_str());
  Serial.printf("  Last Dispensed Order : %s (Duplicate Guard Active)\n", last_dispensed_order_id.length() > 0 ? last_dispensed_order_id.c_str() : "(None)");
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
// 9. WI-FI & CAPTIVE SETUP PORTAL (WITH TFT ON-SCREEN GUI & NETWORK SCAN)
// ==============================================================================
void uiDrawWiFiConnectingScreen(const String& ssid) {
  TFT_display.fillScreen(COLOR_BG);

  // Header Bar
  TFT_display.fillRect(0, 0, 320, 45, COLOR_HEADER);
  TFT_display.drawFastHLine(0, 45, 320, COLOR_CYAN);

  TFT_display.setCursor(15, 14);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(2);
  TFT_display.print("CONNECTING WI-FI");

  // Status Box
  TFT_display.fillRect(15, 65, 290, 380, COLOR_CARD);
  TFT_display.drawRect(15, 65, 290, 380, COLOR_CARD_BORDER);

  TFT_display.setCursor(30, 95);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  TFT_display.print("Target Network:");

  TFT_display.setCursor(30, 130);
  TFT_display.setTextColor(COLOR_YELLOW);
  TFT_display.setTextSize(2);
  TFT_display.printf("SSID: %s", ssid.c_str());

  TFT_display.setCursor(30, 180);
  TFT_display.setTextColor(COLOR_GREEN);
  TFT_display.setTextSize(2);
  TFT_display.print("Negotiating DHCP...");

  TFT_display.setCursor(30, 235);
  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.setTextSize(1);
  TFT_display.print("Connecting: ");
}

void uiDrawWiFiConnectedScreen(const String& ssid, const String& ip) {
  TFT_display.fillScreen(COLOR_BG);

  // Header Bar
  TFT_display.fillRect(0, 0, 320, 45, COLOR_HEADER);
  TFT_display.drawFastHLine(0, 45, 320, COLOR_GREEN);

  TFT_display.setCursor(15, 14);
  TFT_display.setTextColor(COLOR_GREEN);
  TFT_display.setTextSize(2);
  TFT_display.print("WI-FI CONNECTED!");

  // Success Card Box
  TFT_display.fillRect(15, 65, 290, 380, COLOR_CARD);
  TFT_display.drawRect(15, 65, 290, 380, COLOR_GREEN);

  // Big Prominent Green Check Banner
  TFT_display.fillRect(25, 80, 270, 50, COLOR_GREEN);
  TFT_display.setCursor(40, 95);
  TFT_display.setTextColor(COLOR_BLACK);
  TFT_display.setTextSize(2);
  TFT_display.print("NETWORK ONLINE");

  // Details
  TFT_display.setCursor(30, 160);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  TFT_display.printf("SSID: %s", ssid.c_str());

  TFT_display.setCursor(30, 205);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(2);
  TFT_display.printf("IP: %s", ip.c_str());

  TFT_display.setCursor(30, 250);
  TFT_display.setTextColor(COLOR_YELLOW);
  TFT_display.setTextSize(2);
  TFT_display.print("Status: Ready");

  TFT_display.setCursor(30, 305);
  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.setTextSize(1);
  TFT_display.print("Loading Vending Machine Standby QR Screen...");
}

void uiDrawWiFiSetupScreen(const String& apName, const String& ipAddress) {
  TFT_display.fillScreen(COLOR_BG);

  // Header Bar
  TFT_display.fillRect(0, 0, 320, 45, COLOR_HEADER);
  TFT_display.drawFastHLine(0, 45, 320, COLOR_ORANGE);

  TFT_display.setCursor(15, 14);
  TFT_display.setTextColor(COLOR_YELLOW);
  TFT_display.setTextSize(2);
  TFT_display.print("WI-FI SETUP MODE");

  // Error Card
  TFT_display.fillRect(15, 58, 290, 45, COLOR_CARD);
  TFT_display.drawRect(15, 58, 290, 45, COLOR_RED);
  TFT_display.setCursor(25, 72);
  TFT_display.setTextColor(COLOR_RED);
  TFT_display.setTextSize(1);
  TFT_display.print("Wi-Fi Offline! Hotspot Active");

  // Instructions Box
  TFT_display.fillRect(15, 115, 290, 340, COLOR_CARD);
  TFT_display.drawRect(15, 115, 290, 340, COLOR_CARD_BORDER);

  TFT_display.setCursor(25, 130);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(2);
  TFT_display.print("1. Connect Phone:");

  TFT_display.setCursor(25, 160);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  TFT_display.printf("SSID: %s", apName.c_str());

  TFT_display.setCursor(25, 205);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(2);
  TFT_display.print("2. Open Browser:");

  TFT_display.setCursor(25, 235);
  TFT_display.setTextColor(COLOR_GREEN);
  TFT_display.setTextSize(2);
  TFT_display.printf("http://%s", ipAddress.c_str());

  TFT_display.setCursor(25, 280);
  TFT_display.setTextColor(COLOR_YELLOW);
  TFT_display.setTextSize(1);
  TFT_display.print("Select your Wi-Fi, type password & tap Save.");

  TFT_display.setCursor(25, 320);
  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.setTextSize(1);
  TFT_display.print("(Auto-resumes standby in 90s if unconfigured)");
}

void startCaptivePortal() {
  in_ap_setup_mode = true;

  // Start SoftAP immediately without any blocking scans
  String ap_name = "ESP32-Vending-Setup";
  WiFi.disconnect();
  delay(100);
  WiFi.mode(WIFI_AP);
  WiFi.softAP(ap_name.c_str());

  IPAddress apIP = WiFi.softAPIP();
  String ipStr = apIP.toString();

  Serial.println("\n==================================================================");
  Serial.printf("[!] Starting Wi-Fi Captive Setup Hotspot: %s\n", ap_name.c_str());
  Serial.printf("    Connect via Phone/PC and open: http://%s\n", ipStr.c_str());
  Serial.println("==================================================================\n");

  uiDrawWiFiSetupScreen(ap_name, ipStr);

  dnsServer.start(53, "*", apIP);

  // Captive Portal Redirect Handlers for iOS, Android, and Windows
  auto handleCaptiveRedirect = [ipStr]() {
    webServer.sendHeader("Location", "http://" + ipStr + "/", true);
    webServer.send(302, "text/plain", "");
  };

  webServer.on("/generate_204", handleCaptiveRedirect);
  webServer.on("/gen_204", handleCaptiveRedirect);
  webServer.on("/hotspot-detect.html", handleCaptiveRedirect);
  webServer.on("/canonical.html", handleCaptiveRedirect);
  webServer.on("/ncsi.txt", handleCaptiveRedirect);
  webServer.on("/connecttest.txt", handleCaptiveRedirect);

  webServer.on("/", [ap_name, ipStr]() {
    String realMac = getDeviceMacAddress();

    String html = "<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Wi-Fi Setup</title>";
    html += "<style>body{font-family:sans-serif;background:#0b1120;color:#fff;padding:20px;text-align:center;}";
    html += ".card{max-width:360px;margin:0 auto;background:#1e293b;padding:20px;border-radius:12px;border:1px solid #334155;}";
    html += "input{width:100%;box-sizing:border-box;padding:12px;margin:8px 0;background:#0f172a;border:1px solid #475569;border-radius:6px;color:#fff;font-size:15px;}";
    html += "button{width:100%;padding:14px;background:#0284c7;color:#fff;border:none;border-radius:6px;font-size:16px;font-weight:bold;cursor:pointer;margin-top:12px;}";
    html += "</style></head><body><div class='card'>";
    html += "<h2>⚡ Smart Vending Setup</h2>";
    html += "<p style='color:#38bdf8;font-size:13px;'>MAC: " + realMac + "</p>";
    html += "<form action='/save' method='POST'>";
    html += "<label style='display:block;text-align:left;color:#94a3b8;font-size:12px;'>Wi-Fi Name (SSID):</label>";
    html += "<input id='ssidInput' name='ssid' placeholder='Wi-Fi Name (2.4 GHz)' value='" + wifi_ssid + "' required>";
    html += "<label style='display:block;text-align:left;color:#94a3b8;font-size:12px;'>Wi-Fi Password:</label>";
    html += "<input name='pass' type='password' placeholder='Enter Wi-Fi password' required>";
    html += "<label style='display:block;text-align:left;color:#94a3b8;font-size:12px;'>Device ID:</label>";
    html += "<input name='dev_id' placeholder='Machine Device ID' value='" + device_id + "' required>";
    html += "<label style='display:block;text-align:left;color:#94a3b8;font-size:12px;'>Server URL:</label>";
    html += "<input name='srv_url' placeholder='Server Base URL' value='" + server_base_url + "' required>";
    html += "<button type='submit'>💾 Save & Connect Machine</button></form></div></body></html>";
    webServer.send(200, "text/html", html);
  });

  auto handleSaveRequest = [ipStr]() {
    String newSsid = webServer.arg("ssid");
    String newPass = webServer.arg("pass");
    String newDev  = webServer.arg("dev_id");
    String newSrv  = webServer.arg("srv_url");

    newSsid.trim();
    newPass.trim();

    if (newSsid.length() == 0) {
      webServer.send(200, "text/html", "<h3>Error: SSID cannot be empty! <a href='/'>Go Back</a></h3>");
      return;
    }

    if (newDev.length() == 0) newDev = device_id;
    if (newSrv.length() == 0) newSrv = server_base_url;

    savePersistentConfig(newSsid, newPass, newDev, newSrv);

    TFT_display.fillScreen(COLOR_BG);
    TFT_display.setCursor(30, 130);
    TFT_display.setTextColor(COLOR_GREEN);
    TFT_display.setTextSize(2);
    TFT_display.print("Settings Saved!");
    TFT_display.setCursor(30, 170);
    TFT_display.setTextColor(COLOR_WHITE);
    TFT_display.printf("Connecting to: %s", newSsid.c_str());

    String resp = "<!DOCTYPE html><html><body style='background:#0b1120;color:#38bdf8;text-align:center;padding:50px;font-family:sans-serif;'>";
    resp += "<h2>✓ Credentials Saved!</h2>";
    resp += "<p>Connecting to Wi-Fi: <b>" + newSsid + "</b>...</p>";
    resp += "<p>ESP32 is now rebooting. Please wait 10 seconds...</p></body></html>";
    webServer.send(200, "text/html", resp);

    delay(2000);
    ESP.restart();
  };

  webServer.on("/save", handleSaveRequest);

  webServer.onNotFound([ipStr]() {
    webServer.sendHeader("Location", "http://" + ipStr + "/", true);
    webServer.send(302, "text/plain", "");
  });
  webServer.begin();

  unsigned long apStart = millis();
  while (in_ap_setup_mode) {
    dnsServer.processNextRequest();
    webServer.handleClient();

    // 90 second timeout fallback to bench standby if unconfigured
    if (millis() - apStart > 90000 && wifi_ssid.length() > 0) {
      Serial.println("\n[!] Wi-Fi setup timeout (90s). Continuing to Standby Screen...");
      in_ap_setup_mode = false;
      break;
    }
    delay(5);
  }

  webServer.stop();
  dnsServer.stop();
  WiFi.softAPdisconnect(true);
}

void connectToWiFi() {
  if (wifi_ssid.length() == 0) {
    Serial.println("[Wi-Fi] No SSID configured. Continuing directly to Standby Screen...");
    return;
  }

  Serial.printf("\n[Wi-Fi] Connecting to: '%s'...\n", wifi_ssid.c_str());
  uiDrawWiFiConnectingScreen(wifi_ssid);

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.begin(wifi_ssid.c_str(), wifi_pass.c_str());

  int attempts = 0;
  // Wait up to 20 attempts (10 seconds) - never hang on LCD!
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    // Draw animated progress blocks on LCD
    TFT_display.fillRect(110 + (attempts % 16) * 18, 218, 12, 12, COLOR_CYAN);
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[✓] Wi-Fi Connected Successfully!");
    Serial.printf("    Assigned IP : %s\n", WiFi.localIP().toString().c_str());
    Serial.printf("    Signal RSSI : %d dBm\n", WiFi.RSSI());

    // Full on-screen success screen for exactly 2 seconds as requested by user
    uiDrawWiFiConnectedScreen(wifi_ssid, WiFi.localIP().toString());
    delay(2000);
  } else {
    Serial.printf("\n[!] Wi-Fi not connected (status: %d). Launching Standby QR Screen...\n", (int)WiFi.status());
    Serial.println("    (ESP32 will auto-reconnect in background or hold BOOT for Wi-Fi Setup)\n");

    // Display temporary notice on LCD for 1.5 seconds, then PROCEED to QR Screen!
    TFT_display.fillRect(20, 70, 440, 190, COLOR_CARD);
    TFT_display.drawRect(20, 70, 440, 190, COLOR_AMBER);
    TFT_display.setCursor(40, 100);
    TFT_display.setTextColor(COLOR_AMBER);
    TFT_display.setTextSize(2);
    TFT_display.print("WI-FI NOT CONNECTED");
    TFT_display.setCursor(40, 140);
    TFT_display.setTextColor(COLOR_WHITE);
    TFT_display.setTextSize(2);
    TFT_display.print("Launching QR Standby Screen...");
    TFT_display.setCursor(40, 185);
    TFT_display.setTextColor(COLOR_GRAY);
    TFT_display.setTextSize(1);
    TFT_display.print("Auto-reconnecting in background (Hold BOOT for Setup)");
    delay(1500);
  }
}

// 10. REAL-TIME DISPENSE MOTOR EXECUTION ("PLEASE COLLECT MATERIAL")
// ==============================================================================
void dispenseProduct(int slotNumber, float amount, String orderId, String dispenseToken, String productName) {
  // Idempotency Guard: Never dispense the same orderId twice across resets or network retries!
  if (orderId.length() > 0 && orderId == last_dispensed_order_id && !orderId.startsWith("BENCH")) {
    Serial.printf("\n[!] DOUBLE-DISPENSE BLOCKED: Order '%s' was ALREADY dispensed!\n", orderId.c_str());
    Serial.println("    Acknowledging cloud to clear queue without running motor again...");
    if (WiFi.status() == WL_CONNECTED) {
      confirmDispenseToCloud(orderId, dispenseToken);
    }
    return;
  }

  // Persist orderId in RAM and Flash NVS immediately before turning on motor
  last_dispensed_order_id = orderId;
  if (orderId.length() > 0 && !orderId.startsWith("BENCH")) {
    prefs.begin("vending_cfg", false);
    prefs.putString("last_order", orderId);
    prefs.end();
  }

  current_state = STATE_DISPENSING;
  String targetProduct = (productName.length() > 0) ? productName : pending_product_name;

  // Calculate Coin Pulses based on QR Payment Amount (e.g. Rs 1.00 = 1 pulse, Rs 2.00 = 2 pulses, etc.)
  int coinPulses = (int)((amount / COIN_VALUE_PER_PULSE) + 0.5f);
  if (coinPulses < 1) coinPulses = 1;

  Serial.println("\n******************************************************************");
  Serial.printf(">>> 🚀 RAZORPAY PAYMENT VERIFIED (Rs %.2f)! DISPENSING MOTOR %d...\n", amount, slotNumber);
  Serial.printf("    Item       : %s\n", targetProduct.c_str());
  Serial.printf("    Coin Pulses: %d Pulse(s) on GPIO %d (SAME TIME as Motor 1)\n", coinPulses, PIN_COIN_PULSE_OUT);
  Serial.printf("    Auth       : %s\n", dispenseToken.length() > 0 ? dispenseToken.c_str() : "(Standard)");
  Serial.println("******************************************************************");

  // 1. Draw "PAYMENT SUCCESSFUL" & "PLEASE COLLECT MATERIAL" on LCD (Requirement 9)
  uiDrawVendingScreen(slotNumber, amount, targetProduct);

  // 2. Turn ON Motor 1 (GPIO 26)
  setMotor(slotNumber, true);

  // 3. Simultaneously generate Coin Pulses on PIN_COIN_PULSE_OUT while Motor 1 is running!
  const unsigned long pulsePeriod = (unsigned long)(COIN_PULSE_WIDTH_MS + COIN_PULSE_GAP_MS);
  unsigned long totalPulseTime = (unsigned long)coinPulses * pulsePeriod;
  unsigned long totalDispenseDuration = max(MOTOR_DISPENSE_TIME_MS, totalPulseTime);

  unsigned long startTime = millis();
  const int barX = 27;
  const int barY = 144;
  const int barMaxW = 266;
  const int barH = 24;

  int pulsesFired = 0;
  bool pulseActive = false;
  bool materialDropDetected = false;

  while (millis() - startTime < totalDispenseDuration) {
    unsigned long elapsed = millis() - startTime;

    // --- COIN PULSE GENERATOR (Runs at the SAME TIME as Motor 1) ---
    if (elapsed < totalPulseTime) {
      unsigned long pulseCycleTime = elapsed % pulsePeriod;

      if (pulseCycleTime < (unsigned long)COIN_PULSE_WIDTH_MS) {
        if (!pulseActive) {
          setCoinPulsePin(true);
          pulseActive = true;
          pulsesFired++;
          Serial.printf("[🪙 Coin Pulse] Pulse #%d / %d -> ON (GPIO %d)\n", pulsesFired, coinPulses, PIN_COIN_PULSE_OUT);
        }
      } else {
        if (pulseActive) {
          setCoinPulsePin(false);
          pulseActive = false;
          Serial.printf("[🪙 Coin Pulse] Pulse #%d -> OFF\n", pulsesFired);
        }
      }
    } else {
      if (pulseActive) {
        setCoinPulsePin(false);
        pulseActive = false;
      }
    }

    // --- DISPENSE DROP SENSOR (PIN_DISPENSE_SENSOR, GPIO 14) ---
    if (DISPENSE_SENSOR_ENABLED && !materialDropDetected) {
      int sVal = digitalRead(PIN_DISPENSE_SENSOR);
      bool detected = DISPENSE_SENSOR_ACTIVE_LOW ? (sVal == LOW) : (sVal == HIGH);
      if (detected) {
        materialDropDetected = true;
        setMotor(slotNumber, false);
        Serial.printf("[\U0001f4e6 Drop Sensor] MATERIAL DETECTED AT CHUTE (GPIO %d)! Motor turned OFF.\n", PIN_DISPENSE_SENSOR);
      }
    }

    // --- MOTOR DISPENSE CUTOFF (if totalDispenseDuration > default motor runtime) ---
    if (elapsed >= MOTOR_DISPENSE_TIME_MS && elapsed < totalDispenseDuration) {
      setMotor(slotNumber, false);
    }

    // --- LCD PROGRESS BAR ANIMATION ---
    int currentW = (int)((elapsed * (unsigned long)barMaxW) / totalDispenseDuration);
    if (currentW > barMaxW) currentW = barMaxW;
    TFT_display.fillRect(barX, barY, currentW, barH, COLOR_GREEN);

    delay(10);
  }

  // 4. Turn OFF Motor & Coin Pulse
  setCoinPulsePin(false);
  setMotor(slotNumber, false);
  TFT_display.fillRect(barX, barY, barMaxW, barH, COLOR_GREEN);
  Serial.printf("[✓] Slot %d Motor Cycle Complete & %d Coin Pulses Delivered! (Sensor: %s)\n",
                slotNumber, coinPulses, materialDropDetected ? "Material Confirmed Dropped" : "Timer Complete");

  // Decrement inventory if in Stock-Based Mode
  if (stock_management_enabled) {
    if (current_stock > 0) {
      current_stock--;
      prefs.begin("vending_cfg", false);
      prefs.putInt("stock", current_stock);
      prefs.end();
      Serial.printf("[\U0001f4e6 Stock Decremented] Remaining Stock: %d Units\n", current_stock);
      sendHeartbeat();
    } else {
      Serial.println("[\u26a0\ufe0f Stock Warning] Machine was already at 0 stock.");
    }
  }

  // 5. Display "PLEASE COLLECT MATERIAL FROM TRAY"
  uiDrawCompleteScreen();

  // 6. Notify Cloud of successful dispense (one-time dispense confirmation)
  if (WiFi.status() == WL_CONNECTED && orderId.length() > 0 && !orderId.startsWith("BENCH")) {
    confirmDispenseToCloud(orderId, dispenseToken);
  }

  // 7. Hold screen for 4 seconds so customer collects material
  delay(4000);

  // 8. Return to Continuous Standby QR Screen
  current_state = STATE_STANDBY_QR;
  uiDrawStandbyQRScreen();
}

void confirmDispenseToCloud(String orderId, String dispenseToken) {
  WiFiClient client;
  HTTPClient http;
  String endpoint = server_base_url + "/api/v1/orders/" + orderId + "/dispensed";
  if (dispenseToken.length() > 0) {
    endpoint += "?dispense_token=" + dispenseToken;
  }

  http.setConnectTimeout(6000);
  http.setTimeout(6000);
  http.begin(client, endpoint);
  http.addHeader("X-Device-Token", "dev_token_" + device_id);
  int code = http.POST("");
  http.end();
  Serial.printf("[✓] Cloud Inventory Updated: Stock decremented by 1 (HTTP %d).\n", code);
}

// ==============================================================================
// 11. BACKGROUND CLOUD POLLING (CHECKS FOR RAZORPAY PAYMENT MATCH)
// ==============================================================================
void pollPendingDispense() {
  // Guard: In COIN_ONLY mode, online QR check is bypassed
  if (payment_mode.equalsIgnoreCase("COIN_ONLY")) return;

  if (WiFi.status() != WL_CONNECTED) {
    uiUpdateNetworkStatus(NET_STATUS_NO_WIFI);
    return;
  }
  if (current_state != STATE_STANDBY_QR) return;
  if (stock_management_enabled && current_stock <= 0) return;

  WiFiClient client;
  HTTPClient http;
  String endpoint = server_base_url + "/api/v1/orders/pending-dispense/" + device_id;

  http.setConnectTimeout(3000);
  http.setTimeout(3000);
  http.begin(client, endpoint);
  http.addHeader("X-Device-Token", "dev_token_" + device_id);

  int httpCode = http.GET();
  if (httpCode > 0) {
    consecutive_cloud_fails = 0;
    uiUpdateNetworkStatus(NET_STATUS_ONLINE);
  } else {
    consecutive_cloud_fails++;
    if (consecutive_cloud_fails >= 2) {
      uiUpdateNetworkStatus(NET_STATUS_NO_INTERNET);
    }
  }

  if (httpCode == 200) {
    String resp = http.getString();
    StaticJsonDocument<512> doc;
    DeserializationError err = deserializeJson(doc, resp);

    if (!err && doc["dispense_pending"] == true) {
      String orderId = doc["order_id"].as<String>();
      String dispenseToken = doc.containsKey("dispense_token") ? doc["dispense_token"].as<String>() : "";
      int slotNum = doc["slot_number"].as<int>();
      float amount = doc["amount_rupees"].as<float>();
      String prodName = doc.containsKey("product_name") ? doc["product_name"].as<String>() : pending_product_name;
      String orderQrId = doc.containsKey("qr_id") ? doc["qr_id"].as<String>() : "";

      String targetDevId = doc.containsKey("device_id") ? doc["device_id"].as<String>() : device_id;

      // ----------------------------------------------------------------------
      // HARDWARE LEVEL SECURITY: Strict Device ID & QR Code Matching
      // Prevents cross-machine dispensing across 1000+ fleet
      // ----------------------------------------------------------------------
      if (targetDevId.length() > 0 && targetDevId != device_id) {
        Serial.println("\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!");
        Serial.printf("[SECURITY BLOCKED] Cross-machine attempt! Order is for '%s', this machine is '%s'\n", targetDevId.c_str(), device_id.c_str());
        Serial.println("  Dispense REJECTED to protect 1000+ machine fleet isolation!");
        Serial.println("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n");
        http.end();
        return;
      }

      // ----------------------------------------------------------------------
      // VALIDATE CLOUD DISPENSE AUTHORIZATION
      // Cloud dynamically maps uploaded QR codes & TR IDs to this machine,
      // and issues an authenticated single-use dispense_token.
      // ----------------------------------------------------------------------
      if (dispenseToken.length() == 0) {
        Serial.println("[Dispense] Missing cloud authorization token. Dispense rejected.");
        http.end();
        return;
      }

      Serial.printf("[✓ Cloud Authorized] Dispense approved for %s (Order: %s, QR: %s, Price: Rs %.2f)!\n", device_id.c_str(), orderId.c_str(), orderQrId.c_str(), amount);

      // Check Double-Dispense Guard: If orderId was already dispensed, clear cloud and skip motor
      if (orderId.length() > 0 && orderId == last_dispensed_order_id && !orderId.startsWith("BENCH")) {
        Serial.printf("\n[Poll] Double-vend guard: Order '%s' was already dispensed! Re-acknowledging cloud...\n", orderId.c_str());
        http.end();
        confirmDispenseToCloud(orderId, dispenseToken);
        return;
      }

      http.end();

      // Trigger Motor Dispense sequence with unique authorization!
      dispenseProduct(slotNum, amount, orderId, dispenseToken, prodName);
      return;
    }
  } else {
    static unsigned long last_warn_time = 0;
    if (millis() - last_warn_time > 10000) {
      last_warn_time = millis();
      Serial.printf("[Cloud Poll] Response code: %d from %s\n", httpCode, endpoint.c_str());
      if (httpCode < 0) {
        Serial.println("  [!] Connection failed. Please verify:");
        Serial.printf("      1. Server URL is correct (%s)\n", server_base_url.c_str());
        Serial.println("      2. Port 8000 is open in AWS Lightsail Networking firewall");
        Serial.println("      3. FastAPI backend is running on Lightsail");
      }
    }
  }

  http.end();
}

// ==============================================================================
// 12. REMOTE QR & PRICE CONFIGURATION SYNC (VENDOR / MANUFACTURER REAL-TIME UPDATE)
// ==============================================================================
void checkForRemoteQRConfigUpdates() {
  if (WiFi.status() != WL_CONNECTED || current_state != STATE_STANDBY_QR) return;

  WiFiClient client;
  HTTPClient http;
  String endpoint = server_base_url + "/api/v1/orders/qr-config/" + device_id;

  http.setConnectTimeout(2500);
  http.setTimeout(2500);
  http.begin(client, endpoint);

  int httpCode = http.GET();
  if (httpCode > 0) {
    consecutive_cloud_fails = 0;
    uiUpdateNetworkStatus(NET_STATUS_ONLINE);
  } else {
    consecutive_cloud_fails++;
    if (consecutive_cloud_fails >= 2) {
      uiUpdateNetworkStatus(NET_STATUS_NO_INTERNET);
    }
  }

  if (httpCode == 200) {
    String resp = http.getString();
    StaticJsonDocument<2048> doc;
    DeserializationError err = deserializeJson(doc, resp);

    if (!err) {
      int newVersion     = doc["config_version"].as<int>();
      String newVpa      = doc["razorpay_upi_vpa"].as<String>();
      float newAmount    = doc["amount_rupees"].as<float>();
      String newName     = doc["product_name"].as<String>();
      String newQrString = doc.containsKey("qr_payload") ? doc["qr_payload"].as<String>() : "";
      String newTrId     = doc.containsKey("tr_id") ? doc["tr_id"].as<String>() : "";
      String newWifiSsid = doc.containsKey("wifi_ssid") ? doc["wifi_ssid"].as<String>() : "";
      String newWifiPass = doc.containsKey("wifi_password") ? doc["wifi_password"].as<String>() : "";

#if FORCE_STATIC_PROGRAM_CONFIG
      // In Static Program Mode, protect local code overrides from cloud revert
      newQrString = String(STATIC_QR_CODE);
      newName     = String(STATIC_PRODUCT_NAME);
      newAmount   = STATIC_PRICE_RUPEES;
#endif

      bool wifiChanged = (newWifiSsid.length() > 0 && (newWifiSsid != wifi_ssid || newWifiPass != wifi_pass));

      if (wifiChanged) {
        Serial.println("\n==================================================================");
        Serial.println(">>> 📶 REMOTE WI-FI CREDENTIALS RECEIVED FROM CLOUD! <<<");
        Serial.printf("  New SSID     : %s\n", newWifiSsid.c_str());
        Serial.printf("  New Password : %s\n", newWifiPass.length() > 0 ? "********" : "(None)");
        Serial.printf("  New Version  : %d (Old: %d)\n", newVersion, current_config_version);
        Serial.println("  Saving to Flash NVS & Rebooting to Connect...");
        Serial.println("==================================================================\n");

        current_config_version = newVersion;
        wifi_ssid              = newWifiSsid;
        wifi_pass              = newWifiPass;
        if (newVpa.length() > 0) razorpay_upi_vpa = newVpa;
        if (newAmount > 0) pending_amount_rupee = newAmount;
        if (newName.length() > 0) pending_product_name = newName;
        if (!newQrString.startsWith("data:") && newQrString.length() > 0 && newQrString.length() <= 250) {
          custom_qr_code = newQrString;
        }
        if (newTrId.length() > 0) {
          dynamic_tr_id = newTrId;
        }

        // Persist all configuration to Flash NVS
        prefs.begin("vending_cfg", false);
        prefs.putString("ssid", wifi_ssid);
        prefs.putString("pass", wifi_pass);
        prefs.putBool("wifi_remote", true);
        prefs.putString("code_ssid", wifi_ssid);
        prefs.putString("rzp_vpa", razorpay_upi_vpa);
        prefs.putFloat("price", pending_amount_rupee);
        prefs.putString("p_name", pending_product_name);
        prefs.putString("cust_qr", custom_qr_code);
        prefs.putString("tr_id", dynamic_tr_id);
        prefs.putInt("cfg_ver", current_config_version);
        prefs.end();

        // Display update notice on ILI9488 LCD Screen (Vertical 320x480)
        TFT_display.fillScreen(COLOR_BG);
        TFT_display.fillRect(0, 0, 320, 45, COLOR_HEADER);
        TFT_display.drawFastHLine(0, 45, 320, COLOR_CYAN);
        TFT_display.setCursor(15, 14);
        TFT_display.setTextColor(COLOR_CYAN);
        TFT_display.setTextSize(2);
        TFT_display.print("WI-FI CREDENTIALS");

        TFT_display.fillRect(15, 65, 290, 380, COLOR_CARD);
        TFT_display.drawRect(15, 65, 290, 380, COLOR_CARD_BORDER);

        TFT_display.setCursor(30, 95);
        TFT_display.setTextColor(COLOR_WHITE);
        TFT_display.setTextSize(2);
        TFT_display.print("New Network Config:");

        TFT_display.setCursor(30, 135);
        TFT_display.setTextColor(COLOR_YELLOW);
        TFT_display.setTextSize(2);
        TFT_display.printf("SSID: %s", wifi_ssid.c_str());

        TFT_display.setCursor(30, 185);
        TFT_display.setTextColor(COLOR_GREEN);
        TFT_display.setTextSize(2);
        TFT_display.print("Saved to Flash NVS!");

        TFT_display.setCursor(30, 240);
        TFT_display.setTextColor(COLOR_CYAN);
        TFT_display.setTextSize(2);
        TFT_display.print("Rebooting to connect...");

        delay(2000);
        ESP.restart();
      } else {
        bool hasStockModeInCloud = doc.containsKey("stock_management_enabled");
        bool newStockMode = hasStockModeInCloud ? doc["stock_management_enabled"].as<bool>() : stock_management_enabled;

        bool hasStockQtyInCloud = doc.containsKey("current_stock");
        int newStockQty = hasStockQtyInCloud ? doc["current_stock"].as<int>() : current_stock;

        bool stockModeChanged = (hasStockModeInCloud && newStockMode != stock_management_enabled);
        bool stockQtyChanged  = (hasStockQtyInCloud && newStockQty >= 0 && newStockQty != current_stock);

        if (newVersion != current_config_version || newQrString != custom_qr_code || newVpa != razorpay_upi_vpa || newAmount != pending_amount_rupee || newName != pending_product_name || (newTrId.length() > 0 && newTrId != dynamic_tr_id) || stockModeChanged || stockQtyChanged) {
          Serial.println("\n==================================================================");
          Serial.println(">>> \U0001f4f6 REMOTE CONFIG UPDATE RECEIVED FROM PORTAL / CLOUD! <<<     ");
          Serial.printf("  New VPA        : %s\n", newVpa.c_str());
          Serial.printf("  New Price      : Rs %.2f\n", newAmount);
          Serial.printf("  New Product    : %s\n", newName.c_str());
          Serial.printf("  New Version    : %d (Old: %d)\n", newVersion, current_config_version);
          Serial.printf("  New QR Pay     : %s\n", newQrString.c_str());
          Serial.printf("  Stock Mode     : %s (Website Toggle Switch)\n", newStockMode ? "STOCK-BASED" : "WITHOUT-STOCK (Unlimited)");
          Serial.printf("  Stock Quantity : %d Units\n", newStockQty);
          Serial.println("  Updating Flash NVS & Refreshing ILI9488 LCD Screen...");
          Serial.println("==================================================================\n");

          current_config_version   = newVersion;
          razorpay_upi_vpa         = newVpa;
          pending_amount_rupee     = newAmount;
          pending_product_name     = newName;
          stock_management_enabled = newStockMode;
          current_stock            = newStockQty;

          if (!newQrString.startsWith("data:") && newQrString.length() <= 250) {
            custom_qr_code = newQrString;
          }

          if (newTrId.length() > 0) {
            dynamic_tr_id = newTrId;
          }

          // Persist to Flash NVS
          prefs.begin("vending_cfg", false);
          prefs.putString("rzp_vpa", razorpay_upi_vpa);
          prefs.putFloat("price", pending_amount_rupee);
          prefs.putString("p_name", pending_product_name);
          prefs.putString("cust_qr", custom_qr_code);
          prefs.putString("tr_id", dynamic_tr_id);
          prefs.putInt("cfg_ver", current_config_version);
          prefs.putBool("stock_en", stock_management_enabled);
          prefs.putInt("stock", current_stock);
          prefs.end();

          // Immediately Refresh LCD Screen with updated mode & QR!
          uiDrawStandbyQRScreen();
        }
      }
    }
  }
  http.end();
}

// ==============================================================================
// 13. CLOUD HARDWARE HANDSHAKE & DYNAMIC MAC BINDING
// ==============================================================================
bool authenticateWithCloud() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[Cloud] Cannot authenticate: Wi-Fi is not connected.");
    return false;
  }

  WiFiClient client;
  HTTPClient http;
  String endpoint = server_base_url + "/api/v1/device-gateway/authenticate";

  String realMac = getDeviceMacAddress();
  String chipId = "ESP32-CHIP-" + String((uint32_t)ESP.getEfuseMac(), HEX);

  Serial.printf("\n[Cloud] Authenticating Machine '%s' (MAC: %s, Chip: %s) with Server: %s...\n",
                device_id.c_str(), realMac.c_str(), chipId.c_str(), endpoint.c_str());
  http.setConnectTimeout(2500);
  http.setTimeout(2500);
  http.begin(client, endpoint);
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<768> doc;
  doc["device_id"]        = device_id;
  doc["chip_id"]          = chipId;
  doc["mac_address"]      = realMac;
  doc["device_token"]     = device_token;
  doc["firmware_version"] = firmware_version;
  doc["boot_count"]       = 1;
#if FORCE_STATIC_PROGRAM_CONFIG
  doc["custom_qr_code"]   = String(STATIC_QR_CODE);
  doc["product_price"]    = STATIC_PRICE_RUPEES;
  doc["product_name"]     = String(STATIC_PRODUCT_NAME);
#else
  doc["custom_qr_code"]   = custom_qr_code;
  doc["product_price"]    = pending_amount_rupee;
  doc["product_name"]     = pending_product_name;
#endif

  String reqBody;
  serializeJson(doc, reqBody);
  int httpCode = http.POST(reqBody);

  if (httpCode == 200) {
    String resp = http.getString();
    StaticJsonDocument<1024> respDoc;
    deserializeJson(respDoc, resp);

    session_jwt = respDoc["session_token"].as<String>();
    is_authenticated = true;

    if (respDoc.containsKey("device_id")) {
      String assignedId = respDoc["device_id"].as<String>();
      if (assignedId.length() > 0 && assignedId != device_id) {
        Serial.printf("[✓] Cloud automatically identified this MAC as Device ID: %s\n", assignedId.c_str());
        device_id = assignedId;
        device_token = "dev_token_" + device_id;
        prefs.begin("vending_cfg", false);
        prefs.putString("dev_id", device_id);
        prefs.putString("token", device_token);
        prefs.end();
      }
    }
    Serial.println("[✓] Cloud Gateway Handshake SUCCESS! Real MAC Address Bound. Machine is ONLINE.");
    http.end();
    return true;
  } else {
    String respBody = http.getString();
    Serial.printf("[✗] Gateway authentication FAILED (HTTP %d)\n", httpCode);
    if (httpCode < 0) {
      Serial.println("    Connection Error! Possible causes:");
      Serial.println("    1. AWS Lightsail / EC2 Security Group: Port 8000 (TCP) is NOT open.");
      Serial.printf("    2. Cloud URL '%s' is unreachable from this Wi-Fi network.\n", server_base_url.c_str());
    } else {
      Serial.printf("    Server Response: %s\n", respBody.c_str());
    }
  }
  http.end();
  return false;
}

// ==============================================================================
// 14. TELEMETRY HEARTBEAT (KEEPS MACHINE PERMANENTLY ONLINE IN DASHBOARD)
// ==============================================================================
void sendHeartbeat() {
  if (WiFi.status() != WL_CONNECTED) return;

  WiFiClient client;
  HTTPClient http;
  String endpoint = server_base_url + "/api/v1/device-gateway/heartbeat";

  http.setConnectTimeout(5000);
  http.setTimeout(5000);
  http.begin(client, endpoint);
  http.addHeader("Content-Type", "application/json");
  if (session_jwt.length() > 0) {
    http.addHeader("Authorization", "Bearer " + session_jwt);
  }
  http.addHeader("X-Device-ID", device_id);
  http.addHeader("X-Device-Token", device_token);

  StaticJsonDocument<512> doc;
  doc["current_firmware_version"] = firmware_version;
  doc["current_config_version"]   = current_config_version;
  doc["uptime_seconds"]           = millis() / 1000;
  doc["free_heap_bytes"]          = ESP.getFreeHeap();
  doc["wifi_rssi"]                = WiFi.RSSI();
  doc["ip_address"]               = WiFi.localIP().toString();
  doc["current_stock"]            = current_stock;
  doc["stock_enabled"]            = stock_management_enabled;

  String reqBody;
  serializeJson(doc, reqBody);
  int code = http.POST(reqBody);
  if (code > 0) {
    consecutive_cloud_fails = 0;
    uiUpdateNetworkStatus(NET_STATUS_ONLINE);
    if (code == 200) {
      Serial.println("[✓ Heartbeat] Sent successfully to AWS cloud (ONLINE)");
    } else if (code == 401 || code == 403) {
      Serial.printf("[! Heartbeat] Auth expired (HTTP %d). Re-authenticating...\n", code);
      authenticateWithCloud();
    } else {
      Serial.printf("[! Heartbeat] Failed with HTTP code: %d from %s\n", code, endpoint.c_str());
    }
  } else {
    consecutive_cloud_fails++;
    if (consecutive_cloud_fails >= 2) {
      uiUpdateNetworkStatus(NET_STATUS_NO_INTERNET);
    }
    Serial.printf("[! Heartbeat] Network error code %d (No Internet / AWS Unreachable)\n", code);
  }
  http.end();
}

// ==============================================================================
// 15. OVER-THE-AIR (OTA) WIRELESS UPDATE ENGINE
// ==============================================================================
void reportOTAStatus(String deploymentId, String status, String errorMsg) {
  WiFiClient client;
  HTTPClient http;
  String endpoint = server_base_url + "/api/v1/ota/status";
  http.setConnectTimeout(5000);
  http.setTimeout(5000);
  http.begin(client, endpoint);
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<256> doc;
  doc["deployment_id"] = deploymentId;
  doc["status"]        = status;
  if (errorMsg.length() > 0) doc["error_message"] = errorMsg;

  String body;
  serializeJson(doc, body);
  http.POST(body);
  http.end();
}

bool performOTA(String downloadUrl, String deploymentId, size_t binarySize, String targetVer) {
  current_state = STATE_OTA_UPDATING;

  // 1. Draw OTA Update Screen on ILI9488 TFT LCD (Vertical Portrait)
  TFT_display.fillScreen(COLOR_BG);

  // Header Bar
  TFT_display.fillRect(0, 0, 320, 50, COLOR_HEADER);
  TFT_display.drawFastHLine(0, 50, 320, COLOR_CYAN);
  TFT_display.setCursor(20, 14);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(2);
  TFT_display.print("WIRELESS UPDATE (OTA)");

  // Center Info Card
  TFT_display.fillRect(15, 70, 290, 380, COLOR_CARD);
  TFT_display.drawRect(15, 70, 290, 380, COLOR_CARD_BORDER);

  TFT_display.setCursor(25, 95);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  TFT_display.printf("Target: %s", targetVer.c_str());

  TFT_display.setCursor(25, 140);
  TFT_display.setTextColor(COLOR_AMBER);
  TFT_display.setTextSize(2);
  TFT_display.print("DO NOT TURN OFF");
  TFT_display.setCursor(25, 165);
  TFT_display.print("MACHINE POWER!");

  TFT_display.setCursor(25, 210);
  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.setTextSize(1);
  TFT_display.print("Streaming binary into partition...");

  // Notify Cloud Gateway: OTA in Progress
  reportOTAStatus(deploymentId, "DOWNLOADING");

  // Safeguard: If the cloud binary URL is https://, rewrite to server_base_url (plain HTTP)
  // to avoid Nginx "HTTP 400 Plain HTTP request sent to HTTPS port" error on WiFiClient.
  if (downloadUrl.startsWith("https://")) {
    int binIdx = downloadUrl.indexOf("/api/v1/ota/binaries/");
    if (binIdx != -1) {
      downloadUrl = server_base_url + downloadUrl.substring(binIdx);
      Serial.printf("[OTA] Rewrote HTTPS binary URL to plain HTTP endpoint: %s\n", downloadUrl.c_str());
    }
  }

  WiFiClient client;
  HTTPClient http;
  http.setConnectTimeout(15000);
  http.setTimeout(90000);

  if (!http.begin(client, downloadUrl)) {
    Serial.println("[OTA ✗] Failed to connect to binary download endpoint.");
    reportOTAStatus(deploymentId, "FAILED", "Failed to connect to binary endpoint");
    current_state = STATE_STANDBY_QR;
    uiDrawStandbyQRScreen();
    return false;
  }

  int httpCode = http.GET();
  if (httpCode != HTTP_CODE_OK) {
    Serial.printf("[OTA ✗] Binary download returned HTTP %d\n", httpCode);
    reportOTAStatus(deploymentId, "FAILED", "HTTP error " + String(httpCode));
    http.end();
    current_state = STATE_STANDBY_QR;
    uiDrawStandbyQRScreen();
    return false;
  }

  int contentLength = http.getSize() > 0 ? http.getSize() : binarySize;
  if (!Update.begin(contentLength > 0 ? contentLength : UPDATE_SIZE_UNKNOWN, U_FLASH)) {
    Serial.printf("[OTA ✗] Update.begin failed. Error code: %d\n", Update.getError());
    reportOTAStatus(deploymentId, "FAILED", "Partition begin error code " + String(Update.getError()));
    http.end();
    current_state = STATE_STANDBY_QR;
    uiDrawStandbyQRScreen();
    return false;
  }

  Serial.println("[OTA] Writing new firmware to flash partition...");
  WiFiClient *stream = http.getStreamPtr();
  size_t written = Update.writeStream(*stream);

  if (Update.end() && Update.isFinished()) {
    Serial.printf("[✓] OTA SUCCESS! %u bytes written to flash.\n", (unsigned int)written);
    reportOTAStatus(deploymentId, "SUCCESS");

    // Success Screen
    TFT_display.fillRect(25, 260, 270, 60, COLOR_GREEN);
    TFT_display.setCursor(40, 280);
    TFT_display.setTextColor(COLOR_BLACK);
    TFT_display.setTextSize(2);
    TFT_display.print("SUCCESS! REBOOTING...");

    http.end();
    delay(2000);
    ESP.restart();
    return true;
  } else {
    Serial.printf("[OTA ✗] Flashing failed: %u/%u bytes. Error: %d\n", (unsigned int)written, (unsigned int)contentLength, Update.getError());
    reportOTAStatus(deploymentId, "FAILED", "Flash write error code " + String(Update.getError()));
    http.end();

    TFT_display.fillRect(25, 260, 270, 60, COLOR_RED);
    TFT_display.setCursor(40, 280);
    TFT_display.setTextColor(COLOR_WHITE);
    TFT_display.setTextSize(2);
    TFT_display.print("OTA FAILED! RESUMING...");

    delay(3000);
    current_state = STATE_STANDBY_QR;
    uiDrawStandbyQRScreen();
    return false;
  }
}

void checkForPendingOTA() {
  if (WiFi.status() != WL_CONNECTED || current_state != STATE_STANDBY_QR) return;

  WiFiClient client;
  HTTPClient http;
  String endpoint = server_base_url + "/api/v1/ota/check/" + device_id;

  http.setConnectTimeout(6000);
  http.setTimeout(6000);
  http.begin(client, endpoint);

  int httpCode = http.GET();
  if (httpCode > 0) {
    consecutive_cloud_fails = 0;
    uiUpdateNetworkStatus(NET_STATUS_ONLINE);
  } else {
    consecutive_cloud_fails++;
    if (consecutive_cloud_fails >= 2) {
      uiUpdateNetworkStatus(NET_STATUS_NO_INTERNET);
    }
  }

  if (httpCode == 200) {
    String payload = http.getString();
    StaticJsonDocument<1024> doc;
    DeserializationError err = deserializeJson(doc, payload);

    if (!err && doc["has_update"] == true) {
      String deploymentId = doc["deployment_id"].as<String>();
      String targetVer    = doc["version"].as<String>();
      String binaryUrl    = doc["binary_url"].as<String>();
      size_t fileSize     = doc["file_size_bytes"].as<size_t>();

      Serial.println("\n==================================================================");
      Serial.println(">>> ⚡ CLOUD OVER-THE-AIR (OTA) WIRELESS UPDATE DETECTED! <<<      ");
      Serial.printf("  Target Version : %s\n", targetVer.c_str());
      Serial.printf("  Binary Size    : %u bytes\n", (unsigned int)fileSize);
      Serial.printf("  Download URL   : %s\n", binaryUrl.c_str());
      Serial.println("==================================================================");

      http.end();
      performOTA(binaryUrl, deploymentId, fileSize, targetVer);
      return;
    }
  }
  http.end();
}

// ==============================================================================
// 16. HARDWARE MOTOR TEST & BENCH TESTING
// ==============================================================================
void testMotorHardware() {
  Serial.println("\n[⚙️ TEST] Starting Hardware Motor 1 Test (GPIO 26)...");
  setMotor(1, true);
  delay(1500);
  setMotor(1, false);
  Serial.println("[✓] Motor 1 test completed.\n");
}

void printHelpMenu() {
  Serial.println("\n==================================================================");
  Serial.println("           ESP32 RAZORPAY VENDING DESK COMMANDS                   ");
  Serial.println("==================================================================");
  Serial.println("  'p'           : SIMULATE RAZORPAY UPI PAYMENT (Rs 10 -> Motor 1 Vends)");
  Serial.println("  'coin' / 'c'  : SIMULATE COIN ACCEPTOR PULSE (Pulse in -> Mirror to Out -> Vend)");
  Serial.println("  'paymode:qr'  : Set Mode to QR_ONLY");
  Serial.println("  'paymode:coin': Set Mode to COIN_ONLY");
  Serial.println("  'paymode:both': Set Mode to BOTH (QR + Coin)");
  Serial.println("  't'           : Test Motor Hardware (Runs Motor 1 for 1.5s)");
  Serial.println("  's'           : Test Dispense Drop Sensor (GPIO 14)");
  Serial.println("  'stock:20'    : Set Machine Stock to 20 Units");
  Serial.println("  'o'           : Force OTA Update Check Now");
  Serial.println("  'wipe'        : Clear Flash NVS & Factory Reset");
  Serial.println("  'h'           : Show this Help Menu");
  Serial.println("==================================================================\n");
}

// ==============================================================================
// 17. ARDUINO SETUP
// ==============================================================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  // Initialize Wi-Fi station mode immediately so hardware MAC is loaded from eFuse
  WiFi.mode(WIFI_STA);

  Serial.println("\n==================================================================");
  Serial.println("   >>> ESP32 HYBRID VENDING CONTROLLER (QR + COIN + STOCK) <<<          ");
  Serial.println("==================================================================");

  // 1. Initialize Motor, Coin Pulse, Push Buttons & Dispense Sensor Pins
  pinMode(PIN_MOTOR_SLOT_1, OUTPUT);
  pinMode(PIN_MOTOR_SLOT_2, OUTPUT);
  pinMode(PIN_COIN_PULSE_OUT, OUTPUT);
  setMotor(1, false);
  setMotor(2, false);
  setCoinPulsePin(false);

  pinMode(PIN_SETUP_BTN, INPUT_PULLUP);
  
  // Stock Buttons & Drop Sensor
  pinMode(PIN_STOCK_INC_BTN, INPUT_PULLUP);
  pinMode(PIN_STOCK_SAVE_BTN, INPUT_PULLUP);
  pinMode(PIN_DISPENSE_SENSOR, INPUT_PULLUP);

  // Coin Acceptor Pulse Input Pin with Interrupt
  pinMode(PIN_COIN_INPUT, COIN_INPUT_ACTIVE_LOW ? INPUT_PULLUP : INPUT_PULLDOWN);
  attachInterrupt(digitalPinToInterrupt(PIN_COIN_INPUT), isrCoinAcceptorPulse, COIN_INPUT_ACTIVE_LOW ? FALLING : RISING);

  // 2. Initialize ILI9488 TFT LCD Display in VERTICAL PORTRAIT MODE
  Serial.println("[TFT] Initializing 320x480 ILI9488 SPI LCD Display (Vertical Portrait)...");
  TFT_display.begin();
  TFT_display.setRotation(TFT_ROTATION); // 0 = Vertical Portrait (320 wide x 480 high)
  TFT_display.fillScreen(COLOR_BG);

  // Splash Screen
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(3);
  TFT_display.setCursor(25, 180);
  TFT_display.print("SMART VENDING");
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  TFT_display.setCursor(45, 230);
  TFT_display.print("Vertical Node Active");
  delay(1200);

  // 3. Load Flash NVS Config
  loadPersistentConfig();

  // 4. Connect to Wi-Fi (Shows "Wi-Fi Connected Successfully!" for 2 seconds)
  connectToWiFi();

  // 5. Render Standby QR Screen IMMEDIATELY so QR code and product are visible with zero delay!
  uiDrawStandbyQRScreen();
  printHelpMenu();

  // 6. Fast non-blocking cloud handshake (occurs in background after QR is already displayed)
  if (WiFi.status() == WL_CONNECTED) {
    authenticateWithCloud();
    sendHeartbeat();
  }

  Serial.println("[✓] Zero-Touch Vending Ready! Customer can scan QR anytime.");
}

// ==============================================================================
// 18. ARDUINO MAIN LOOP
// ==============================================================================

// ==============================================================================
// 16. PHYSICAL COIN ACCEPTOR PULSE ENGINE (RECEIVES & ECHOES TO GPIO 25 & VENDS)
// ==============================================================================
void processCoinAcceptorInput() {
  if (current_state == STATE_DISPENSING || is_refill_mode) return;

  // 1. When a new pulse arrives from coin acceptor, mirror it immediately to PIN_COIN_PULSE_OUT!
  if (isr_new_coin_pulse) {
    isr_new_coin_pulse = false;
    
    // Echo pulse to PIN_COIN_PULSE_OUT (GPIO 25)
    setCoinPulsePin(true);
    delay(COIN_PULSE_WIDTH_MS);
    setCoinPulsePin(false);
    
    Serial.printf("[🪙 Coin In] Pulse #%d received on GPIO %d -> Mirrored to GPIO %d!\n",
                  isr_coin_pulses_received, PIN_COIN_INPUT, PIN_COIN_PULSE_OUT);
  }

  // 2. Pulse Train Complete (Idle timeout reached after last pulse)
  if (isr_coin_pulses_received > 0 && (millis() - isr_last_coin_pulse_time >= COIN_INPUT_IDLE_TIMEOUT_MS)) {
    int totalPulses = isr_coin_pulses_received;
    isr_coin_pulses_received = 0; // Reset for next insertion

    Serial.println("\n******************************************************************");
    Serial.printf(">>> 🪙 COIN TRANSACTION RECEIVED! %d Pulse(s) on GPIO %d <<<\n", totalPulses, PIN_COIN_INPUT);
    Serial.printf("    Payment Acceptance Mode: %s\n", payment_mode.c_str());
    Serial.println("******************************************************************");

    // Guard: Check if machine is set to QR_ONLY mode
    if (payment_mode.equalsIgnoreCase("QR_ONLY")) {
      Serial.println("[! COIN IGNORED] Machine is currently in QR_ONLY mode. Coin payment rejected.");
      return;
    }

    // Guard: Check Out of Stock
    if (stock_management_enabled && current_stock <= 0) {
      Serial.println("[! COIN REJECTED] Machine is OUT OF STOCK. Cannot dispense.");
      uiDrawOutOfStockScreen();
      delay(2500);
      uiDrawStandbyQRScreen();
      return;
    }

    // Trigger Dispense! Whenever coin pulse is received, it vends!
    String coinOrderId = "COIN-P" + String(totalPulses) + "-" + String(millis());
    Serial.printf(">>> 🚀 Triggering Dispense Cycle for Coin Payment (OrderId: %s)...\n", coinOrderId.c_str());
    dispenseProduct(1, pending_amount_rupee, coinOrderId, "", pending_product_name);
  }
}

void loop() {
  // ----------------------------------------------------------------------------
  // 1. PUSH SWITCH 1 (GPIO 32): CYCLE STOCK NUMBER (1 to 50, then wraps to 1)
  // ----------------------------------------------------------------------------
  static unsigned long last_inc_press = 0;
  if (digitalRead(PIN_STOCK_INC_BTN) == LOW && (millis() - last_inc_press > 220)) {
    last_inc_press = millis();
    if (!is_refill_mode) {
      is_refill_mode = true;
      refill_stock_count = (current_stock > 0 && current_stock <= MAX_SELECTABLE_STOCK) ? current_stock : 1;
    }
    refill_stock_count++;
    if (refill_stock_count > MAX_SELECTABLE_STOCK) {
      refill_stock_count = 1; // Wraps back from 50 to 1!
    }
    last_refill_activity_time = millis();
    Serial.printf("[🔘 SW 1 Pressed] Stock Count: %d / %d\n", refill_stock_count, MAX_SELECTABLE_STOCK);
    uiDrawStockRefillScreen(refill_stock_count);
  }

  // ----------------------------------------------------------------------------
  // 2. PUSH SWITCH 2 (GPIO 33): SAVE STOCK TO MACHINE OR HOLD 4S TO TOGGLE MODE
  // ----------------------------------------------------------------------------
  if (digitalRead(PIN_STOCK_SAVE_BTN) == LOW) {
    unsigned long savePressStart = millis();
    bool modeToggled = false;

    // Check if operator is holding SW 2 for 4 seconds to toggle Stock Mode
    while (digitalRead(PIN_STOCK_SAVE_BTN) == LOW) {
      if (millis() - savePressStart > 4000) {
        stock_management_enabled = !stock_management_enabled;
        prefs.begin("vending_cfg", false);
        prefs.putBool("stock_en", stock_management_enabled);
        prefs.end();
        Serial.printf("\n[⚙️ MODE TOGGLE] Machine Mode changed to: %s\n", 
                      stock_management_enabled ? "STOCK-BASED (Inventory tracking active)" : "WITHOUT STOCK (Continuous vending)");
        uiDrawModeToggledScreen(stock_management_enabled);
        delay(2500);
        is_refill_mode = false;
        uiDrawStandbyQRScreen();
        modeToggled = true;
        break;
      }
      delay(40);
    }

    // Normal Click on SW 2 -> Save and apply current stock!
    if (!modeToggled) {
      if (is_refill_mode) {
        current_stock = refill_stock_count;
        prefs.begin("vending_cfg", false);
        prefs.putInt("stock", current_stock);
        prefs.end();
        Serial.printf("\n[💾 SW 2 Pressed] Stock updated to: %d Units! Saved to Flash NVS.\n", current_stock);
        uiDrawStockSavedScreen(current_stock);
        delay(2000);
        is_refill_mode = false;
        sendHeartbeat();
        uiDrawStandbyQRScreen();
      } else {
        // Direct click from standby opens Refill Menu with current stock
        is_refill_mode = true;
        refill_stock_count = (current_stock > 0 && current_stock <= MAX_SELECTABLE_STOCK) ? current_stock : 10;
        last_refill_activity_time = millis();
        uiDrawStockRefillScreen(refill_stock_count);
      }
    }
  }

  // ----------------------------------------------------------------------------
  // 3. REFILL MENU AUTO-TIMEOUT (25 Seconds of Inactivity)
  // ----------------------------------------------------------------------------
  if (is_refill_mode && (millis() - last_refill_activity_time > REFILL_TIMEOUT_MS)) {
    Serial.println("[Stock Menu] Inactive for 25s. Auto-exiting to Standby QR Screen...");
    is_refill_mode = false;
    uiDrawStandbyQRScreen();
  }

  // 4. Setup / Wi-Fi Hotspot Button Check: Hold BOOT (GPIO 0) for 3 seconds to launch Wi-Fi Setup Hotspot
  if (digitalRead(PIN_SETUP_BTN) == LOW) {
    unsigned long pressStart = millis();
    while (digitalRead(PIN_SETUP_BTN) == LOW) {
      if (millis() - pressStart > 3000) {
        Serial.println("\n[!] BOOT BUTTON HELD! Starting Wi-Fi Configuration Hotspot on Screen...");
        startCaptivePortal();
        uiDrawStandbyQRScreen();
        break;
      }
      delay(50);
    }
  }

  // 2. Wi-Fi Background Auto-Reconnect & Real-Time Status Detection
  static unsigned long last_wifi_reconnect_time = 0;
  if (WiFi.status() != WL_CONNECTED) {
    uiUpdateNetworkStatus(NET_STATUS_NO_WIFI);
    if (millis() - last_wifi_reconnect_time > 15000) {
      last_wifi_reconnect_time = millis();
      Serial.println("[Wi-Fi] Attempting background reconnection to " + wifi_ssid + "...");
      WiFi.reconnect();
    }
  }

  // 3. Serial Commands (Desk Bench Testing & Setup)
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.length() > 0) {
      if (cmd == "w" || cmd == "W") {
        Serial.println("\n[⚡ WI-FI] Manual Wi-Fi configuration hotspot triggered from Serial!");
        startCaptivePortal();
        uiDrawStandbyQRScreen();
      } else if (cmd == "p" || cmd == "P") {
        Serial.println("\n[💳 TEST] SIMULATING RAZORPAY PAYMENT RECEIVED (Rs " + String(pending_amount_rupee, 2) + ")!");
        dispenseProduct(1, pending_amount_rupee, "BENCH-TEST-" + String(millis()));
      } else if (cmd == "t" || cmd == "T") {
        testMotorHardware();
      } else if (cmd == "s" || cmd == "S") {
        int sVal = digitalRead(PIN_DISPENSE_SENSOR);
        bool detected = DISPENSE_SENSOR_ACTIVE_LOW ? (sVal == LOW) : (sVal == HIGH);
        Serial.printf("\n[Dispense Sensor Test] GPIO %d Raw Value: %d -> Material Detected: %s\n", 
                      PIN_DISPENSE_SENSOR, sVal, detected ? "YES (Material in beam)" : "NO (Chute clear)");
      } else if (cmd.equalsIgnoreCase("stock")) {
        Serial.printf("\n[Stock Status] Mode: %s | Active Stock: %d / %d Units\n",
                      stock_management_enabled ? "STOCK-BASED" : "WITHOUT STOCK (Unlimited)",
                      current_stock, MAX_SELECTABLE_STOCK);
      } else if (cmd.startsWith("stock:") || cmd.startsWith("STOCK:")) {
        int val = cmd.substring(6).toInt();
        if (val >= 0 && val <= 500) {
          current_stock = val;
          prefs.begin("vending_cfg", false);
          prefs.putInt("stock", current_stock);
          prefs.end();
          Serial.printf("\n[✓ Stock Updated] Stock set to %d units via Serial! Saved to NVS.\n", current_stock);
          uiDrawStandbyQRScreen();
        }
      } else if (cmd.equalsIgnoreCase("mode:on")) {
        stock_management_enabled = true;
        prefs.begin("vending_cfg", false);
        prefs.putBool("stock_en", true);
        prefs.end();
        Serial.println("\n[Mode Changed] Stock-Based Machine Mode ENABLED.");
        uiDrawStandbyQRScreen();
      } else if (cmd.equalsIgnoreCase("mode:off")) {
        stock_management_enabled = false;
        prefs.begin("vending_cfg", false);
        prefs.putBool("stock_en", false);
        prefs.end();
        Serial.println("\n[Mode Changed] Without-Stock Machine Mode (Unlimited) ENABLED.");
        uiDrawStandbyQRScreen();
      } else if (cmd == "m" || cmd == "M") {
        stock_management_enabled = !stock_management_enabled;
        prefs.begin("vending_cfg", false);
        prefs.putBool("stock_en", stock_management_enabled);
        prefs.end();
        Serial.printf("\n[Mode Toggled] Stock Mode is now: %s\n", stock_management_enabled ? "STOCK-BASED" : "WITHOUT STOCK");
        uiDrawStandbyQRScreen();
      } else if (cmd.equalsIgnoreCase("coin") || cmd.equalsIgnoreCase("c")) {
        Serial.println("\n[🪙 SIMULATE COIN] Simulating 1 Coin Pulse from Serial...");
        isr_coin_pulses_received = 1;
        isr_new_coin_pulse = true;
        isr_last_coin_pulse_time = millis() - 350;
      } else if (cmd.equalsIgnoreCase("coin2") || cmd.equalsIgnoreCase("c2")) {
        Serial.println("\n[🪙 SIMULATE COIN] Simulating 2 Coin Pulses from Serial...");
        isr_coin_pulses_received = 2;
        isr_new_coin_pulse = true;
        isr_last_coin_pulse_time = millis() - 350;
      } else if (cmd.equalsIgnoreCase("paymode:qr")) {
        payment_mode = "QR_ONLY";
        prefs.begin("vending_cfg", false);
        prefs.putString("pay_mode", payment_mode);
        prefs.end();
        Serial.println("\n[Payment Mode] Switched to QR_ONLY mode via Serial.");
        uiDrawStandbyQRScreen();
      } else if (cmd.equalsIgnoreCase("paymode:coin")) {
        payment_mode = "COIN_ONLY";
        prefs.begin("vending_cfg", false);
        prefs.putString("pay_mode", payment_mode);
        prefs.end();
        Serial.println("\n[Payment Mode] Switched to COIN_ONLY mode via Serial.");
        uiDrawStandbyQRScreen();
      } else if (cmd.equalsIgnoreCase("paymode:both")) {
        payment_mode = "BOTH";
        prefs.begin("vending_cfg", false);
        prefs.putString("pay_mode", payment_mode);
        prefs.end();
        Serial.println("\n[Payment Mode] Switched to BOTH (QR + COIN) mode via Serial.");
        uiDrawStandbyQRScreen();
      } else if (cmd == "o" || cmd == "O") {
        Serial.println("\n[⚡ OTA] Manually triggering OTA check from Serial...");
        checkForPendingOTA();
      } else if (cmd == "c" || cmd == "C" || cmd.equalsIgnoreCase("wipe")) {
        Serial.println("\n[🧹 NVS] Clearing all persistent settings from Flash NVS...");
        prefs.begin("vending_cfg", false);
        prefs.clear();
        prefs.end();
        Serial.println("[✓] NVS wiped clean! Rebooting ESP32...");
        delay(500);
        ESP.restart();
      } else if (cmd == "h" || cmd == "H" || cmd == "?") {
        printHelpMenu();
      }
    }
  }

  // 4. Periodic Telemetry Heartbeat (keeps machine strictly ONLINE in cloud)
  if (millis() - last_heartbeat_time >= HEARTBEAT_INTERVAL_MS) {
    last_heartbeat_time = millis();
    sendHeartbeat();
  }

  // 5. Operations in Standby QR State (Paused while setting stock in Refill Menu)
  if (current_state == STATE_STANDBY_QR && !is_refill_mode) {
    // 5a. Real-time polling for incoming Razorpay payment
    if (millis() - last_poll_time >= POLL_INTERVAL_MS) {
      last_poll_time = millis();
      pollPendingDispense();
    }

    // 5b. Periodic check for pending Over-The-Air (OTA) updates
    if (millis() - last_ota_check_time >= OTA_CHECK_INTERVAL_MS) {
      last_ota_check_time = millis();
      checkForPendingOTA();
    }

    // 5c. Periodic check for QR & Price changes by Vendor / Manufacturer
    if (millis() - last_config_check_time >= CONFIG_CHECK_INTERVAL_MS) {
      last_config_check_time = millis();
      checkForRemoteQRConfigUpdates();
    }
  }

  delay(20);
}
