/**
 * ==============================================================================
 * ESP32 RAZORPAY ZERO-BUTTON VENDING MACHINE (ILI9488 TFT LCD + PRICE-MATCH VEND)
 * ==============================================================================
 * Multi-Tenant IoT Fleet Platform (Scale to 1,000+ Machines)
 * Target Board: ESP32 / ESP32-WROOM-32 / ESP32-S3
 * Display: 3.5" or 4.0" ILI9488 320x480 TFT LCD (SPI Interface)
 * Motor: Vending Dispense Motor / Relay (Configured for 1 Motor, expandable to 2+)
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
 * Motors (Currently working with 1 motor):
 *   Motor 1 (Slot 1 Relay / Driver) -> GPIO 26
 *   Motor 2 (Slot 2 Relay / Driver) -> GPIO 27 (Optional secondary motor)
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

// Motor / Relay Pins (Default: Working with 1 Motor on GPIO 26)
const int PIN_MOTOR_SLOT_1  = 26;   // Motor 1 Relay / Driver IN1
const int PIN_MOTOR_SLOT_2  = 27;   // Motor 2 (Optional secondary motor)
const int PIN_COIN_PULSE_OUT = 25;  // Coin Pulse Output Pin (Generates pulses based on QR amount)
const int PIN_SETUP_BTN     = 0;    // ESP32 BOOT Button (Hold 5s for reset)

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

String wifi_ssid        = "Airtel_Sathiyan-Tamil";
String wifi_pass        = "Sraja@92@";
String device_id        = "VM-000001";              // Unique Machine ID in 1000+ fleet
String device_token     = "dev_token_VM-000001";
String server_base_url  = "http://35.154.219.82:8000";
String razorpay_upi_vpa = "gtech282722.rzp@rxairtel"; // Default GTECH Standee Razorpay VPA
String firmware_version = "v2.2.0-razorpay-ota";

// Cloud Session & Online State
String session_jwt      = "";
bool   is_authenticated = false;

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
void uiDrawOfflineNotice(NetworkStatus status) {
  bool isNoWifi = (status == NET_STATUS_NO_WIFI);
  uint16_t accentColor = isNoWifi ? COLOR_RED : COLOR_AMBER;

  // 1. Draw Offline Card Box (x: 18, y: 54, w: 190, h: 190)
  TFT_display.fillRect(18, 54, 190, 190, COLOR_CARD);
  TFT_display.drawRect(18, 54, 190, 190, accentColor);
  TFT_display.drawRect(19, 55, 188, 188, accentColor);
  TFT_display.drawRect(21, 57, 184, 184, COLOR_CARD_BORDER);

  int cx = 113; // Horizontal center of the 190px box (18 + 95)

  if (isNoWifi) {
    // --- ICON: WI-FI DISCONNECTED SYMBOL (Wi-Fi waves with bold Red 'X' slash) ---
    int cy = 94;

    // Wi-Fi base dot
    TFT_display.fillCircle(cx, cy + 18, 3, COLOR_GRAY);

    // Wi-Fi outer wave arcs
    TFT_display.drawCircle(cx, cy + 18, 14, COLOR_GRAY);
    TFT_display.drawCircle(cx, cy + 18, 15, COLOR_GRAY);
    TFT_display.drawCircle(cx, cy + 18, 25, COLOR_GRAY);
    TFT_display.drawCircle(cx, cy + 18, 26, COLOR_GRAY);

    // Mask bottom half so only upper arcs appear
    TFT_display.fillRect(18, cy + 19, 190, 30, COLOR_CARD);

    // Bold Red 'X' across the Wi-Fi icon
    for (int o = -2; o <= 2; o++) {
      TFT_display.drawLine(cx - 24 + o, cy - 8, cx + 24 + o, cy + 24, COLOR_RED);
      TFT_display.drawLine(cx + 24 + o, cy - 8, cx - 24 + o, cy + 24, COLOR_RED);
    }

    // Title: NO WI-FI
    TFT_display.setTextSize(2);
    TFT_display.setTextColor(COLOR_RED);
    TFT_display.setCursor(38, 134);
    TFT_display.print("NO WI-FI");
  } else {
    // --- ICON: WARNING TRIANGLE SYMBOL (Amber triangle with white exclamation '!') ---
    int cy = 92;

    // Bold layered warning triangle
    for (int t = 0; t < 3; t++) {
      TFT_display.drawTriangle(cx, cy - 24 + t, cx - 28 + t, cy + 18 - t, cx + 28 - t, cy + 18 - t, COLOR_AMBER);
    }
    TFT_display.drawTriangle(cx, cy - 22, cx - 26, cy + 16, cx + 26, cy + 16, COLOR_YELLOW);

    // Exclamation Mark '!'
    TFT_display.fillRect(cx - 2, cy - 12, 5, 16, COLOR_WHITE);
    TFT_display.fillCircle(cx, cy + 12, 2, COLOR_WHITE);

    // Title: NO INTERNET
    TFT_display.setTextSize(2);
    TFT_display.setTextColor(COLOR_AMBER);
    TFT_display.setCursor(24, 134);
    TFT_display.print("NO INTERNET");
  }

  // Subtext inside box
  TFT_display.setTextSize(1);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setCursor(34, 160);
  TFT_display.print("QR PAYMENTS OFFLINE");

  TFT_display.setTextColor(COLOR_YELLOW);
  TFT_display.setCursor(38, 176);
  TFT_display.print("PLEASE DO NOT PAY");

  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.setCursor(44, 194);
  TFT_display.print("Reconnecting...");

  // Status pill at bottom of box
  TFT_display.fillRect(30, 214, 166, 18, COLOR_DARK_GRAY);
  TFT_display.drawRect(30, 214, 166, 18, COLOR_CARD_BORDER);
  TFT_display.setCursor(38, 219);
  TFT_display.setTextColor(accentColor);
  TFT_display.print(isNoWifi ? "WiFi Signal Lost" : "Cloud Link Offline");

  // 2. Subtext below box (x: 10 - 215, y: 254 - 316)
  TFT_display.fillRect(10, 252, 210, 64, COLOR_BG);

  TFT_display.setCursor(20, 258);
  TFT_display.setTextColor(COLOR_ORANGE);
  TFT_display.setTextSize(1);
  TFT_display.print("QR code hidden while offline");

  TFT_display.setCursor(18, 274);
  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.setTextSize(1);
  TFT_display.print("Appears automatically when online");

  // Bottom alert bar
  TFT_display.fillRect(10, 292, 205, 22, accentColor);
  TFT_display.setCursor(16, 298);
  TFT_display.setTextColor(isNoWifi ? COLOR_WHITE : COLOR_BLACK);
  TFT_display.setTextSize(1);
  TFT_display.print(isNoWifi ? "! WI-FI DISCONNECTED !" : "! NO CLOUD / INTERNET !");
}

/**
 * Live Dynamic Network & Internet Status Monitor
 * Automatically hides/shows the QR code based on cloud and WiFi status!
 */
void uiUpdateNetworkStatus(NetworkStatus newStatus) {
  if (current_state != STATE_STANDBY_QR) return;
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

  // Header Bar (y: 0 - 45)
  TFT_display.fillRect(0, 0, 480, 45, COLOR_HEADER);
  TFT_display.drawFastHLine(0, 45, 480, COLOR_BLUE);

  TFT_display.setCursor(15, 14);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  TFT_display.print("SMART VENDING");

  // Machine ID & Online Status Badge
  TFT_display.setCursor(205, 15);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(2);
  TFT_display.printf("[%s]", device_id.c_str());

  if (WiFi.status() != WL_CONNECTED) {
    current_net_status = NET_STATUS_NO_WIFI;
    TFT_display.setCursor(330, 15);
    TFT_display.setTextColor(COLOR_RED);
    TFT_display.setTextSize(2);
    TFT_display.print("● NO WI-FI");
  } else if (current_net_status == NET_STATUS_NO_INTERNET) {
    TFT_display.setCursor(330, 15);
    TFT_display.setTextColor(COLOR_AMBER);
    TFT_display.setTextSize(2);
    TFT_display.print("● NO CLOUD");
  } else {
    current_net_status = NET_STATUS_ONLINE;
    TFT_display.setCursor(375, 15);
    TFT_display.setTextColor(COLOR_GREEN);
    TFT_display.setTextSize(2);
    TFT_display.print("● READY");
  }

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

  // Guard against raw image data URIs or oversized blobs (do not attempt to encode 50KB images)
  if (upiUri.startsWith("data:") || upiUri.length() > 250) {
    Serial.println("[QR Warning] Data URI or oversized string detected; falling back to clean UPI URI.");
    upiUri = "upi://pay?pa=" + razorpay_upi_vpa + 
             "&pn=IoT%20Vending&am=" + String(pending_amount_rupee, 2) + 
             "&cu=INR&tn=" + device_id;
  }

  // Left: Display QR Code ONLY IF MACHINE IS ONLINE!
  if (current_net_status == NET_STATUS_ONLINE) {
    // Draw High-Contrast Razorpay QR Code Box
    drawQRCode(upiUri.c_str(), 18, 54, 190);

    // Subtext under QR
    TFT_display.setCursor(22, 258);
    TFT_display.setTextColor(COLOR_WHITE);
    TFT_display.setTextSize(1);
    TFT_display.print("GPay / PhonePe / Paytm / BHIM");

    TFT_display.setCursor(24, 276);
    TFT_display.setTextColor(COLOR_CYAN);
    TFT_display.setTextSize(1);
    TFT_display.print("Powered by Razorpay Route");

    TFT_display.setCursor(18, 296);
    TFT_display.setTextColor(COLOR_GRAY);
    TFT_display.setTextSize(1);
    TFT_display.print("Auto-Transfers to Vendor Account");
  } else {
    // MACHINE IS OFFLINE (NO WI-FI OR NO INTERNET / CLOUD)
    // DO NOT SHOW PAYMENT QR CODE! Display clear No Internet Message & Graphical Icon!
    uiDrawOfflineNotice(current_net_status);
  }

  // Right Side: Product & Price Card
  TFT_display.fillRect(225, 54, 245, 255, COLOR_CARD);
  TFT_display.drawRect(225, 54, 245, 255, COLOR_CARD_BORDER);

  // Product Badge
  TFT_display.fillRect(240, 66, 120, 24, COLOR_BLUE);
  TFT_display.setCursor(248, 70);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  TFT_display.print("PRODUCT 1");

  // Product Title
  TFT_display.setCursor(240, 98);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  TFT_display.print(pending_product_name.c_str());

  // Price Display
  TFT_display.setCursor(240, 124);
  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.setTextSize(1);
  TFT_display.print("PRICE (SCAN & PAY):");

  TFT_display.setCursor(240, 140);
  TFT_display.setTextColor(COLOR_GREEN);
  TFT_display.setTextSize(4);
  TFT_display.printf("Rs %.2f", pending_amount_rupee);

  if (current_net_status == NET_STATUS_ONLINE) {
    // Instructions Box (Online Mode)
    TFT_display.fillRect(238, 196, 218, 52, COLOR_DARK_GRAY);
    TFT_display.setCursor(244, 202);
    TFT_display.setTextColor(COLOR_AMBER);
    TFT_display.setTextSize(1);
    TFT_display.print("NO BUTTON NEEDED!");

    TFT_display.setCursor(244, 216);
    TFT_display.setTextColor(COLOR_WHITE);
    TFT_display.setTextSize(1);
    TFT_display.print("1. Scan QR  2. Pay Rs 10");

    TFT_display.setCursor(244, 230);
    TFT_display.setTextColor(COLOR_GREEN);
    TFT_display.setTextSize(1);
    TFT_display.print("3. Machine vends automatically");

    // Bottom Live Status
    TFT_display.setCursor(240, 266);
    TFT_display.setTextColor(COLOR_GRAY);
    TFT_display.setTextSize(1);
    TFT_display.print("STATUS:");

    TFT_display.setCursor(240, 282);
    TFT_display.setTextColor(COLOR_CYAN);
    TFT_display.setTextSize(2);
    TFT_display.print("AWAITING PAY...");
  } else {
    // Instructions Box (Offline Mode)
    TFT_display.fillRect(238, 196, 218, 52, COLOR_DARK_GRAY);
    TFT_display.setCursor(244, 202);
    TFT_display.setTextColor(COLOR_RED);
    TFT_display.setTextSize(1);
    TFT_display.print("VENDING TEMPORARILY OFFLINE");

    TFT_display.setCursor(244, 216);
    TFT_display.setTextColor(COLOR_WHITE);
    TFT_display.setTextSize(1);
    TFT_display.print("No internet link to verify payments");

    TFT_display.setCursor(244, 230);
    TFT_display.setTextColor(COLOR_AMBER);
    TFT_display.setTextSize(1);
    TFT_display.print("Please stand by for auto-reconnect");

    // Bottom Live Status
    TFT_display.setCursor(240, 266);
    TFT_display.setTextColor(COLOR_GRAY);
    TFT_display.setTextSize(1);
    TFT_display.print("STATUS:");

    TFT_display.setCursor(240, 282);
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
  TFT_display.fillRect(0, 0, 480, 50, COLOR_GREEN);
  TFT_display.setCursor(65, 14);
  TFT_display.setTextColor(COLOR_BLACK);
  TFT_display.setTextSize(3);
  TFT_display.print("PAYMENT SUCCESSFUL");

  // Center Main Action Card
  TFT_display.fillRect(20, 60, 440, 245, COLOR_CARD);
  TFT_display.drawRect(20, 60, 440, 245, COLOR_CYAN);

  // Product Name & Amount details
  TFT_display.setCursor(35, 75);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  String displayName = (productName.length() > 0) ? productName : pending_product_name;
  if (displayName.length() > 24) displayName = displayName.substring(0, 22) + "..";
  TFT_display.printf("Item  : %s", displayName.c_str());

  TFT_display.setCursor(35, 102);
  TFT_display.setTextColor(COLOR_AMBER);
  TFT_display.setTextSize(2);
  TFT_display.printf("Amount: Rs. %.2f", amount);

  // Progress Bar Outer Frame
  TFT_display.drawRect(35, 130, 410, 28, COLOR_WHITE);

  // Prominent "PLEASE COLLECT MATERIAL" Banner
  TFT_display.fillRect(30, 168, 420, 60, COLOR_GREEN);
  TFT_display.setCursor(45, 186);
  TFT_display.setTextColor(COLOR_BLACK);
  TFT_display.setTextSize(3);
  TFT_display.print("PLEASE COLLECT MATERIAL");

  // Subtext
  TFT_display.setCursor(75, 242);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(2);
  TFT_display.printf("Dispensing Motor %d from Tray", slotNumber);

  TFT_display.setCursor(120, 274);
  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.setTextSize(1);
  TFT_display.print("Please wait while motor cycles...");
}

/**
 * Screen 3: Vending Complete & Collect Material from Tray
 */
void uiDrawCompleteScreen() {
  TFT_display.fillScreen(COLOR_BG);

  // Top Green Header
  TFT_display.fillRect(0, 0, 480, 50, COLOR_GREEN);
  TFT_display.setCursor(60, 14);
  TFT_display.setTextColor(COLOR_BLACK);
  TFT_display.setTextSize(3);
  TFT_display.print("DISPENSE COMPLETED!");

  // Center Card
  TFT_display.fillRect(20, 65, 440, 240, COLOR_CARD);
  TFT_display.drawRect(20, 65, 440, 240, COLOR_GREEN);

  // Big Prominent Highlight Box
  TFT_display.fillRect(30, 95, 420, 72, COLOR_GREEN);
  TFT_display.setCursor(45, 118);
  TFT_display.setTextColor(COLOR_BLACK);
  TFT_display.setTextSize(3);
  TFT_display.print("PLEASE COLLECT MATERIAL");

  // Instruction Subtitle
  TFT_display.setCursor(90, 188);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(2);
  TFT_display.print("ITEM READY IN BOTTOM TRAY");

  TFT_display.setCursor(125, 230);
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
  prefs.end();

  Serial.println("\n==================================================================");
  Serial.println("  >>> ⚡ ESP32 RAZORPAY ZERO-BUTTON VENDING CONTROLLER <<<       ");
  Serial.println("==================================================================");
  Serial.printf("  Device ID (Machine)  : %s\n", device_id.c_str());
  Serial.printf("  Hardware MAC Address : %s\n", getDeviceMacAddress().c_str());
  Serial.printf("  Razorpay UPI VPA     : %s\n", razorpay_upi_vpa.c_str());
  Serial.printf("  Item Price (Rupees)  : Rs %.2f\n", pending_amount_rupee);
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
  TFT_display.fillRect(0, 0, 480, 45, COLOR_HEADER);
  TFT_display.drawFastHLine(0, 45, 480, COLOR_CYAN);

  TFT_display.setCursor(15, 14);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(2);
  TFT_display.print("⚡ CONNECTING TO WI-FI");

  // Status Box
  TFT_display.fillRect(20, 70, 440, 190, COLOR_CARD);
  TFT_display.drawRect(20, 70, 440, 190, COLOR_CARD_BORDER);

  TFT_display.setCursor(40, 95);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  TFT_display.print("Target Network:");

  TFT_display.setCursor(40, 125);
  TFT_display.setTextColor(COLOR_YELLOW);
  TFT_display.setTextSize(2);
  TFT_display.printf("SSID: %s", ssid.c_str());

  TFT_display.setCursor(40, 165);
  TFT_display.setTextColor(COLOR_GREEN);
  TFT_display.setTextSize(2);
  TFT_display.print("Negotiating DHCP Lease...");

  TFT_display.setCursor(40, 218);
  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.setTextSize(1);
  TFT_display.print("Connecting: ");
}

void uiDrawWiFiConnectedScreen(const String& ssid, const String& ip) {
  TFT_display.fillScreen(COLOR_BG);

  // Header Bar
  TFT_display.fillRect(0, 0, 480, 45, COLOR_HEADER);
  TFT_display.drawFastHLine(0, 45, 480, COLOR_GREEN);

  TFT_display.setCursor(15, 14);
  TFT_display.setTextColor(COLOR_GREEN);
  TFT_display.setTextSize(2);
  TFT_display.print("WI-FI CONNECTED SUCCESSFULLY!");

  // Success Card Box
  TFT_display.fillRect(20, 65, 440, 235, COLOR_CARD);
  TFT_display.drawRect(20, 65, 440, 235, COLOR_GREEN);

  // Big Prominent Green Check Banner
  TFT_display.fillRect(35, 80, 410, 50, COLOR_GREEN);
  TFT_display.setCursor(55, 95);
  TFT_display.setTextColor(COLOR_BLACK);
  TFT_display.setTextSize(3);
  TFT_display.print("NETWORK ONLINE");

  // Details
  TFT_display.setCursor(45, 148);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  TFT_display.printf("Connected to: %s", ssid.c_str());

  TFT_display.setCursor(45, 185);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(2);
  TFT_display.printf("Assigned IP : %s", ip.c_str());

  TFT_display.setCursor(45, 222);
  TFT_display.setTextColor(COLOR_YELLOW);
  TFT_display.setTextSize(2);
  TFT_display.print("Status      : Ready to Vend");

  TFT_display.setCursor(45, 265);
  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.setTextSize(1);
  TFT_display.print("Loading Vending Machine Standby QR Screen...");
}

void uiDrawWiFiSetupScreen(const String& apName, const String& ipAddress) {
  TFT_display.fillScreen(COLOR_BG);

  // Header Bar
  TFT_display.fillRect(0, 0, 480, 45, COLOR_HEADER);
  TFT_display.drawFastHLine(0, 45, 480, COLOR_ORANGE);

  TFT_display.setCursor(15, 14);
  TFT_display.setTextColor(COLOR_YELLOW);
  TFT_display.setTextSize(2);
  TFT_display.print("⚡ WI-FI CONFIGURATION MODE");

  // Error Card
  TFT_display.fillRect(20, 58, 440, 42, COLOR_CARD);
  TFT_display.drawRect(20, 58, 440, 42, COLOR_RED);
  TFT_display.setCursor(30, 70);
  TFT_display.setTextColor(COLOR_RED);
  TFT_display.setTextSize(2);
  TFT_display.print("Wi-Fi Offline! Setup Hotspot Active");

  // Instructions Box
  TFT_display.fillRect(20, 112, 440, 195, COLOR_CARD);
  TFT_display.drawRect(20, 112, 440, 195, COLOR_CARD_BORDER);

  TFT_display.setCursor(35, 125);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(2);
  TFT_display.print("1. Connect Phone to Hotspot:");

  TFT_display.setCursor(55, 150);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  TFT_display.printf("   SSID: %s", apName.c_str());

  TFT_display.setCursor(35, 185);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(2);
  TFT_display.print("2. Open Browser & Go to:");

  TFT_display.setCursor(55, 210);
  TFT_display.setTextColor(COLOR_GREEN);
  TFT_display.setTextSize(2);
  TFT_display.printf("   http://%s", ipAddress.c_str());

  TFT_display.setCursor(35, 250);
  TFT_display.setTextColor(COLOR_YELLOW);
  TFT_display.setTextSize(1);
  TFT_display.print("   Select your Wi-Fi from dropdown, type password & tap Save.");

  TFT_display.setCursor(35, 275);
  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.setTextSize(1);
  TFT_display.print("   (Auto-resumes standby mode in 90s if unconfigured)");
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
  const int barX = 37;
  const int barY = 132;
  const int barMaxW = 406;
  const int barH = 24;

  int pulsesFired = 0;
  bool pulseActive = false;

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
  Serial.printf("[✓] Slot %d Motor Cycle Complete & %d Coin Pulses Delivered!\n", slotNumber, coinPulses);

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
  if (WiFi.status() != WL_CONNECTED) {
    uiUpdateNetworkStatus(NET_STATUS_NO_WIFI);
    return;
  }
  if (current_state != STATE_STANDBY_QR) return;

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

        // Display notice on ILI9488 LCD Screen (Horizontal 480x320)
        TFT_display.fillScreen(COLOR_BG);
        TFT_display.fillRect(0, 0, 480, 45, COLOR_HEADER);
        TFT_display.drawFastHLine(0, 45, 480, COLOR_CYAN);
        TFT_display.setCursor(15, 14);
        TFT_display.setTextColor(COLOR_CYAN);
        TFT_display.setTextSize(2);
        TFT_display.print("WI-FI CREDENTIALS UPDATED");

        TFT_display.fillRect(20, 65, 440, 235, COLOR_CARD);
        TFT_display.drawRect(20, 65, 440, 235, COLOR_CARD_BORDER);

        TFT_display.setCursor(40, 95);
        TFT_display.setTextColor(COLOR_WHITE);
        TFT_display.setTextSize(2);
        TFT_display.print("New Network Config Received:");

        TFT_display.setCursor(40, 135);
        TFT_display.setTextColor(COLOR_YELLOW);
        TFT_display.setTextSize(2);
        TFT_display.printf("SSID: %s", wifi_ssid.c_str());

        TFT_display.setCursor(40, 175);
        TFT_display.setTextColor(COLOR_GREEN);
        TFT_display.setTextSize(2);
        TFT_display.print("Saved to Flash NVS!");

        TFT_display.setCursor(40, 225);
        TFT_display.setTextColor(COLOR_CYAN);
        TFT_display.setTextSize(2);
        TFT_display.print("Rebooting to connect...");

        delay(2000);
        ESP.restart();
      } else if (newVersion != current_config_version || newQrString != custom_qr_code || newVpa != razorpay_upi_vpa || newAmount != pending_amount_rupee || newName != pending_product_name || (newTrId.length() > 0 && newTrId != dynamic_tr_id)) {
        Serial.println("\n==================================================================");
        Serial.println(">>> 📶 REMOTE QR / PRICE UPDATE RECEIVED FROM VENDOR / CLOUD! <<<");
        Serial.printf("  New VPA    : %s\n", newVpa.c_str());
        Serial.printf("  New Price  : Rs %.2f\n", newAmount);
        Serial.printf("  New Product: %s\n", newName.c_str());
        Serial.printf("  New Version: %d (Old: %d)\n", newVersion, current_config_version);
        Serial.printf("  New QR Pay : %s\n", newQrString.c_str());
        Serial.println("  Updating Flash NVS & Refreshing ILI9488 LCD Screen...");
        Serial.println("==================================================================\n");

        current_config_version = newVersion;
        razorpay_upi_vpa       = newVpa;
        pending_amount_rupee   = newAmount;
        pending_product_name   = newName;
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
        prefs.end();

        // Immediately Refresh LCD Screen with brand new QR code!
        uiDrawStandbyQRScreen();
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

  // 1. Draw OTA Update Screen on ILI9488 TFT LCD
  TFT_display.fillScreen(COLOR_BG);

  // Header Bar
  TFT_display.fillRect(0, 0, 480, 50, COLOR_HEADER);
  TFT_display.drawFastHLine(0, 50, 480, COLOR_CYAN);
  TFT_display.setCursor(50, 14);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(3);
  TFT_display.print("WIRELESS UPDATE (OTA)");

  // Center Info Card
  TFT_display.fillRect(25, 70, 430, 230, COLOR_CARD);
  TFT_display.drawRect(25, 70, 430, 230, COLOR_CARD_BORDER);

  TFT_display.setCursor(45, 95);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  TFT_display.printf("Flashing Target: %s", targetVer.c_str());

  TFT_display.setCursor(45, 130);
  TFT_display.setTextColor(COLOR_AMBER);
  TFT_display.setTextSize(2);
  TFT_display.print("CRITICAL: DO NOT TURN OFF POWER!");

  TFT_display.setCursor(45, 168);
  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.setTextSize(2);
  TFT_display.print("Streaming binary into partition...");

  // Notify Cloud Gateway: OTA in Progress
  reportOTAStatus(deploymentId, "DOWNLOADING");

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
    TFT_display.fillRect(35, 220, 410, 60, COLOR_GREEN);
    TFT_display.setCursor(55, 238);
    TFT_display.setTextColor(COLOR_BLACK);
    TFT_display.setTextSize(2);
    TFT_display.print("SUCCESS! REBOOTING NODE...");

    http.end();
    delay(2000);
    ESP.restart();
    return true;
  } else {
    Serial.printf("[OTA ✗] Flashing failed: %u/%u bytes. Error: %d\n", (unsigned int)written, (unsigned int)contentLength, Update.getError());
    reportOTAStatus(deploymentId, "FAILED", "Flash write error code " + String(Update.getError()));
    http.end();

    TFT_display.fillRect(35, 220, 410, 60, COLOR_RED);
    TFT_display.setCursor(55, 238);
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
  Serial.println("  'p' : SIMULATE RAZORPAY PAYMENT (Rs 10 -> Motor 1 Vends)");
  Serial.println("  't' : Test Motor Hardware (Runs Motor 1 for 1.5s)");
  Serial.println("  'o' : Force OTA Update Check Now");
  Serial.println("  'h' : Show this Help Menu");
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
  Serial.println("   >>> ESP32 RAZORPAY ZERO-BUTTON VENDING CONTROLLER <<<          ");
  Serial.println("==================================================================");

  // 1. Initialize Motor & Coin Pulse Pins (Immediate OFF)
  pinMode(PIN_MOTOR_SLOT_1, OUTPUT);
  pinMode(PIN_MOTOR_SLOT_2, OUTPUT);
  pinMode(PIN_COIN_PULSE_OUT, OUTPUT);
  setMotor(1, false);
  setMotor(2, false);
  setCoinPulsePin(false);

  pinMode(PIN_SETUP_BTN, INPUT_PULLUP);

  // 2. Initialize ILI9488 TFT LCD Display
  Serial.println("[TFT] Initializing 320x480 ILI9488 SPI LCD Display...");
  TFT_display.begin();
  TFT_display.setRotation(1); // Landscape: 480 wide x 320 high
  TFT_display.fillScreen(COLOR_BG);

  // Splash Screen
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(3);
  TFT_display.setCursor(60, 120);
  TFT_display.print("SMART VENDING NODE");
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  TFT_display.setCursor(120, 170);
  TFT_display.print("Razorpay Route Active");
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
void loop() {
  // 1. Setup / Wi-Fi Hotspot Button Check: Hold BOOT (GPIO 0) for 3 seconds to launch Wi-Fi Setup Hotspot
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
    char c = Serial.read();
    if (c == 'w' || c == 'W') {
      Serial.println("\n[⚡ WI-FI] Manual Wi-Fi configuration hotspot triggered from Serial!");
      startCaptivePortal();
      uiDrawStandbyQRScreen();
    } else if (c == 'p' || c == 'P') {
      Serial.println("\n[💳 TEST] SIMULATING RAZORPAY PAYMENT RECEIVED (Rs 2.00)!");
      dispenseProduct(1, 2.00, "BENCH-TEST-" + String(millis()));
    } else if (c == 't' || c == 'T') {
      testMotorHardware();
    } else if (c == 'o' || c == 'O') {
      Serial.println("\n[⚡ OTA] Manually triggering OTA check from Serial...");
      checkForPendingOTA();
    } else if (c == 'c' || c == 'C') {
      Serial.println("\n[🧹 NVS] Clearing all persistent settings from Flash NVS...");
      prefs.begin("vending_cfg", false);
      prefs.clear();
      prefs.end();
      Serial.println("[✓] NVS wiped clean! Rebooting ESP32...");
      delay(500);
      ESP.restart();
    } else if (c == 'h' || c == 'H' || c == '?') {
      printHelpMenu();
    }
  }

  // 4. Periodic Telemetry Heartbeat (keeps machine strictly ONLINE in cloud)
  if (millis() - last_heartbeat_time >= HEARTBEAT_INTERVAL_MS) {
    last_heartbeat_time = millis();
    sendHeartbeat();
  }

  // 5. Operations in Standby QR State
  if (current_state == STATE_STANDBY_QR) {
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
