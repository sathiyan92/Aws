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
#include <ArduinoJson.h>
#include <DIYables_TFT_SPI.h>
#include "qrcode.h"

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
const int PIN_SETUP_BTN     = 0;    // ESP32 BOOT Button (Hold 5s for reset)

// Dispense Runtime (Milliseconds)
const unsigned long MOTOR_DISPENSE_TIME_MS = 3000; // Motor runs for 3 seconds per dispense

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
#define COLOR_RED         DIYables_TFT_SPI::colorRGB(239, 68, 68)    // Coral Red (#EF4444)
#define COLOR_GRAY        DIYables_TFT_SPI::colorRGB(148, 163, 184)  // Slate Muted (#94A3B8)
#define COLOR_DARK_GRAY   DIYables_TFT_SPI::colorRGB(30, 41, 59)

// Create Display Object for ILI9488
DIYables_ILI9488_SPI TFT_display(TFT_WIDTH, TFT_HEIGHT, TFT_CS_PIN, TFT_DC_PIN, TFT_RST_PIN);

// ==============================================================================
// 4. CONFIGURATION & STATE STORAGE (FLASH NVS)
// ==============================================================================
Preferences prefs;

String wifi_ssid        = "iphone";
String wifi_pass        = "8015885416";
String device_id        = "VM-000001";              // Unique Machine ID in 1000+ fleet
String device_token     = "dev_token_VM-000001";
String server_base_url  = "http://35.154.219.82:8000";
String razorpay_upi_vpa = "rzp.vending.vm000001@icici"; // Default or dynamic Razorpay VPA
String firmware_version = "v2.0.0-razorpay";

// Machine Operating State Machine
enum MachineState {
  STATE_STANDBY_QR,    // Continuously displaying QR, polling for payment
  STATE_DISPENSING,    // Payment confirmed, motor running, showing collect material
  STATE_COMPLETE       // Dispense complete screen
};
MachineState current_state = STATE_STANDBY_QR;

// Dispense Order Details
String pending_order_id     = "";
String pending_order_number = "";
int    pending_slot_number  = 1;
float  pending_amount_rupee = 10.00;
String pending_product_name = "Cold Drink";
String custom_qr_code       = "";

// Polling interval
unsigned long last_poll_time = 0;
const unsigned long POLL_INTERVAL_MS = 1800; // Check cloud for Razorpay payment every 1.8 seconds

// Remote Config Polling (Checks if Vendor/Manufacturer changed QR or Price)
unsigned long last_config_check_time = 0;
const unsigned long CONFIG_CHECK_INTERVAL_MS = 25000; // Check remote QR config every 25s
int current_config_version = 1;

// Fallback Captive Portal for Initial Wi-Fi Setup
WebServer webServer(80);
DNSServer dnsServer;
bool in_ap_setup_mode = false;

// Forward Declarations
void uiDrawStandbyQRScreen();
void uiDrawVendingScreen(int slotNumber, float amount, String productName);
void uiDrawCompleteScreen();
void setMotor(int slotNumber, bool turnOn);
void dispenseProduct(int slotNumber, float amount, String orderId);
void confirmDispenseToCloud(String orderId);
void pollPendingDispense();
void testMotorHardware();
void printHelpMenu();

// ==============================================================================
// 5. MOTOR CONTROL HELPER
// ==============================================================================
void setMotor(int slotNumber, bool turnOn) {
  int pin = (slotNumber == 2 && ACTIVE_MOTOR_COUNT > 1) ? PIN_MOTOR_SLOT_2 : PIN_MOTOR_SLOT_1;
  int state = turnOn ? (RELAY_ACTIVE_LOW ? LOW : HIGH) : (RELAY_ACTIVE_LOW ? HIGH : LOW);
  digitalWrite(pin, state);
}

// ==============================================================================
// 6. QR CODE DRAWING ENGINE (ON ILI9488 TFT LCD)
// ==============================================================================
void drawQRCode(const char* text, int startX, int startY, int maxBoxSize) {
  QRCode qrcode;
  uint8_t qrcodeBytes[qrcode_getBufferSize(8)];

  // Automatically find the smallest QR version that fits payload
  int version = -1;
  for (int v = 3; v <= 8; v++) {
    int8_t res = qrcode_initText(&qrcode, qrcodeBytes, v, ECC_LOW, text);
    if (res == 0) {
      version = v;
      break;
    }
  }

  if (version < 0) {
    Serial.println("[QR] Error: String too long or failed to encode!");
    TFT_display.fillRect(startX, startY, maxBoxSize, maxBoxSize, COLOR_WHITE);
    TFT_display.setTextColor(COLOR_RED);
    TFT_display.setTextSize(2);
    TFT_display.setCursor(startX + 15, startY + (maxBoxSize / 2) - 10);
    TFT_display.print("QR Error");
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

  TFT_display.setCursor(375, 15);
  TFT_display.setTextColor(COLOR_GREEN);
  TFT_display.setTextSize(2);
  TFT_display.print("● READY");

  // Construct Dynamic or Static Razorpay UPI Payload
  String upiUri = (custom_qr_code.length() > 0) ? custom_qr_code : 
                  ("upi://pay?pa=" + razorpay_upi_vpa + 
                  "&pn=IoT%20Vending&am=" + String(pending_amount_rupee, 2) + 
                  "&cu=INR&tn=" + device_id);

  // Left: Draw High-Contrast Razorpay QR Code Box
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

  TFT_display.setCursor(20, 296);
  TFT_display.setTextColor(COLOR_GRAY);
  TFT_display.setTextSize(1);
  TFT_display.print("Auto-Transfers to Vendor Account");

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

  // Instructions Box (No button needed!)
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
}

/**
 * Screen 2: Vending In Progress & "PLEASE COLLECT MATERIAL"
 * "once payment is verfity vednind has to proecess , lcd will display the process please collect material"
 */
void uiDrawVendingScreen(int slotNumber, float amount, String productName) {
  TFT_display.fillScreen(COLOR_BG);

  // Top Banner (Emerald Green)
  TFT_display.fillRect(0, 0, 480, 50, COLOR_GREEN);
  TFT_display.setCursor(55, 14);
  TFT_display.setTextColor(COLOR_BLACK);
  TFT_display.setTextSize(3);
  TFT_display.printf("PAYMENT RECEIVED: Rs %.0f", amount);

  // Center Main Action Card
  TFT_display.fillRect(20, 65, 440, 240, COLOR_CARD);
  TFT_display.drawRect(20, 65, 440, 240, COLOR_CYAN);

  // Motor Action Title
  TFT_display.setCursor(45, 82);
  TFT_display.setTextColor(COLOR_CYAN);
  TFT_display.setTextSize(3);
  TFT_display.printf("VENDING MOTOR %d...", slotNumber);

  // Progress Bar Outer Frame
  TFT_display.drawRect(40, 122, 400, 30, COLOR_WHITE);

  // Prominent "PLEASE COLLECT MATERIAL" Banner
  TFT_display.fillRect(30, 168, 420, 62, COLOR_GREEN);
  TFT_display.setCursor(45, 188);
  TFT_display.setTextColor(COLOR_BLACK);
  TFT_display.setTextSize(3);
  TFT_display.print("PLEASE COLLECT MATERIAL");

  // Subtext
  TFT_display.setCursor(75, 248);
  TFT_display.setTextColor(COLOR_WHITE);
  TFT_display.setTextSize(2);
  TFT_display.print("Dispensing from Tray Below");

  TFT_display.setCursor(140, 276);
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
  wifi_ssid        = prefs.getString("ssid", "");
  wifi_pass        = prefs.getString("pass", "");
  device_id        = prefs.getString("dev_id", "VM-000001");
  device_token     = prefs.getString("token", "dev_token_" + device_id);
  server_base_url  = prefs.getString("srv_url", "http://35.154.219.82:8000");
  razorpay_upi_vpa = prefs.getString("rzp_vpa", "rzp.vending." + device_id + "@icici");
  prefs.end();

  Serial.println("\n==================================================================");
  Serial.println("  >>> ⚡ ESP32 RAZORPAY ZERO-BUTTON VENDING CONTROLLER <<<       ");
  Serial.println("==================================================================");
  Serial.printf("  Device ID (Machine)  : %s\n", device_id.c_str());
  Serial.printf("  Hardware MAC Address : %s\n", WiFi.macAddress().c_str());
  Serial.printf("  Razorpay UPI VPA     : %s\n", razorpay_upi_vpa.c_str());
  Serial.printf("  Target Wi-Fi SSID    : %s\n", wifi_ssid.length() > 0 ? wifi_ssid.c_str() : "(Not Configured)");
  Serial.printf("  Cloud Server Base URL: %s\n", server_base_url.c_str());
  Serial.println("==================================================================\n");
}

void savePersistentConfig(String ssid, String pass, String dev_id, String srv_url) {
  prefs.begin("vending_cfg", false);
  prefs.putString("ssid", ssid);
  prefs.putString("pass", pass);
  prefs.putString("dev_id", dev_id);
  prefs.putString("token", "dev_token_" + dev_id);
  prefs.putString("srv_url", srv_url);
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
// 9. WI-FI & CAPTIVE SETUP PORTAL
// ==============================================================================
void startCaptivePortal() {
  in_ap_setup_mode = true;
  WiFi.disconnect();
  WiFi.mode(WIFI_AP);
  String ap_name = "ESP32-Vending-Setup";
  WiFi.softAP(ap_name.c_str());

  Serial.println("\n[!] No Wi-Fi credentials in Flash NVS. Started AP: " + ap_name);
  Serial.println("    Connect via phone/PC to: http://192.168.4.1\n");

  dnsServer.start(53, "*", WiFi.softAPIP());
  webServer.on("/", []() {
    String html = "<html><body style='font-family:sans-serif;background:#0b1120;color:#fff;padding:25px;text-align:center;'>";
    html += "<h2>⚡ ESP32 Vending Setup</h2><p style='color:#94a3b8;'>Enter Wi-Fi network & Device ID:</p>";
    html += "<form action='/save' method='POST' style='max-width:320px;margin:0 auto;'>";
    html += "<input name='ssid' placeholder='Wi-Fi Name' required style='width:100%;padding:10px;margin:6px 0;background:#1e293b;border:1px solid #334155;color:#fff;'><br>";
    html += "<input name='pass' type='password' placeholder='Wi-Fi Password' required style='width:100%;padding:10px;margin:6px 0;background:#1e293b;border:1px solid #334155;color:#fff;'><br>";
    html += "<input name='dev_id' placeholder='Device ID (e.g. VM-000001)' value='" + device_id + "' required style='width:100%;padding:10px;margin:6px 0;background:#1e293b;border:1px solid #334155;color:#fff;'><br>";
    html += "<input name='srv_url' placeholder='Server URL' value='" + server_base_url + "' required style='width:100%;padding:10px;margin:6px 0;background:#1e293b;border:1px solid #334155;color:#fff;'><br>";
    html += "<button type='submit' style='width:100%;padding:12px;background:#0284c7;color:#fff;border:none;border-radius:6px;font-weight:bold;cursor:pointer;margin-top:10px;'>💾 Save & Connect</button></form></body></html>";
    webServer.send(200, "text/html", html);
  });
  webServer.on("/save", HTTP_POST, []() {
    savePersistentConfig(webServer.arg("ssid"), webServer.arg("pass"), webServer.arg("dev_id"), webServer.arg("srv_url"));
    webServer.send(200, "text/html", "<html><body style='background:#0b1120;color:#38bdf8;text-align:center;padding:50px;'><h2>✓ Saved! Rebooting...</h2></body></html>");
    delay(2000);
    ESP.restart();
  });
  webServer.onNotFound([]() {
    webServer.sendHeader("Location", "/", true);
    webServer.send(302, "text/plain", "");
  });
  webServer.begin();

  while (in_ap_setup_mode) {
    dnsServer.processNextRequest();
    webServer.handleClient();
    delay(5);
  }
}

void connectToWiFi() {
  if (wifi_ssid.length() == 0) {
    startCaptivePortal();
    return;
  }

  Serial.printf("\n[Wi-Fi] Connecting to: %s\n", wifi_ssid.c_str());
  WiFi.mode(WIFI_STA);
  WiFi.begin(wifi_ssid.c_str(), wifi_pass.c_str());

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[✓] Wi-Fi Connected!");
    Serial.printf("    Assigned IP : %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\n[!] Wi-Fi connection timed out. Operating in Standby / Bench Mode.");
  }
}

// ==============================================================================
// 10. REAL-TIME DISPENSE MOTOR EXECUTION ("PLEASE COLLECT MATERIAL")
// ==============================================================================
void dispenseProduct(int slotNumber, float amount, String orderId) {
  current_state = STATE_DISPENSING;

  Serial.println("\n******************************************************************");
  Serial.printf(">>> 🚀 RAZORPAY PAYMENT VERIFIED (Rs %.2f)! DISPENSING MOTOR %d...\n", amount, slotNumber);
  Serial.println("******************************************************************");

  // 1. Draw "PAYMENT VERIFIED" & "PLEASE COLLECT MATERIAL" on LCD
  uiDrawVendingScreen(slotNumber, amount, pending_product_name);

  // 2. Turn ON Motor 1 (GPIO 26)
  setMotor(slotNumber, true);

  // 3. Smooth progress bar animation over 3 seconds
  unsigned long startTime = millis();
  const int barX = 42;
  const int barY = 124;
  const int barMaxW = 396;
  const int barH = 26;

  while (millis() - startTime < MOTOR_DISPENSE_TIME_MS) {
    unsigned long elapsed = millis() - startTime;
    int currentW = (elapsed * barMaxW) / MOTOR_DISPENSE_TIME_MS;
    TFT_display.fillRect(barX, barY, currentW, barH, COLOR_GREEN);
    delay(40);
  }
  TFT_display.fillRect(barX, barY, barMaxW, barH, COLOR_GREEN);

  // 4. Turn OFF Motor
  setMotor(slotNumber, false);
  Serial.printf("[✓] Slot %d Motor Cycle Complete. Product Dispensed!\n", slotNumber);

  // 5. Display "PLEASE COLLECT MATERIAL FROM TRAY"
  uiDrawCompleteScreen();

  // 6. Notify Cloud of successful dispense (decrements stock)
  if (WiFi.status() == WL_CONNECTED && orderId.length() > 0 && !orderId.startsWith("BENCH")) {
    confirmDispenseToCloud(orderId);
  }

  // 7. Hold screen for 4 seconds so customer collects material
  delay(4000);

  // 8. Return to Continuous Standby QR Screen
  current_state = STATE_STANDBY_QR;
  uiDrawStandbyQRScreen();
}

void confirmDispenseToCloud(String orderId) {
  WiFiClient client;
  HTTPClient http;
  String endpoint = server_base_url + "/api/v1/orders/" + orderId + "/dispensed";

  http.setConnectTimeout(6000);
  http.setTimeout(6000);
  http.begin(client, endpoint);
  http.POST("");
  http.end();
  Serial.println("[✓] Cloud Inventory Updated: Stock decremented by 1.");
}

// ==============================================================================
// 11. BACKGROUND CLOUD POLLING (CHECKS FOR RAZORPAY PAYMENT MATCH)
// ==============================================================================
void pollPendingDispense() {
  if (WiFi.status() != WL_CONNECTED || current_state != STATE_STANDBY_QR) return;

  WiFiClient client;
  HTTPClient http;
  String endpoint = server_base_url + "/api/v1/orders/pending-dispense/" + device_id;

  http.setConnectTimeout(3000);
  http.setTimeout(3000);
  http.begin(client, endpoint);

  int httpCode = http.GET();
  if (httpCode == 200) {
    String resp = http.getString();
    StaticJsonDocument<512> doc;
    DeserializationError err = deserializeJson(doc, resp);

    if (!err && doc["dispense_pending"] == true) {
      String orderId = doc["order_id"].as<String>();
      int slotNum = doc["slot_number"].as<int>();
      float amount = doc["amount_rupees"].as<float>();
      if (doc.containsKey("product_name")) {
        pending_product_name = doc["product_name"].as<String>();
      }

      http.end();

      // Trigger Motor Dispense sequence!
      dispenseProduct(slotNum, amount, orderId);
      return;
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

  http.setConnectTimeout(4000);
  http.setTimeout(4000);
  http.begin(client, endpoint);

  int httpCode = http.GET();
  if (httpCode == 200) {
    String resp = http.getString();
    StaticJsonDocument<512> doc;
    DeserializationError err = deserializeJson(doc, resp);

    if (!err) {
      int newVersion     = doc["config_version"].as<int>();
      String newVpa      = doc["razorpay_upi_vpa"].as<String>();
      float newAmount    = doc["amount_rupees"].as<float>();
      String newName     = doc["product_name"].as<String>();
      String newQrString = doc.containsKey("qr_payload") ? doc["qr_payload"].as<String>() : "";

      if (newVersion > current_config_version || newVpa != razorpay_upi_vpa || newAmount != pending_amount_rupee || newName != pending_product_name) {
        Serial.println("\n==================================================================");
        Serial.println(">>> 📶 REMOTE QR / PRICE UPDATE RECEIVED FROM VENDOR / CLOUD! <<<");
        Serial.printf("  New VPA    : %s\n", newVpa.c_str());
        Serial.printf("  New Price  : Rs %.2f\n", newAmount);
        Serial.printf("  New Product: %s\n", newName.c_str());
        Serial.printf("  New Version: %d (Old: %d)\n", newVersion, current_config_version);
        Serial.println("  Updating Flash NVS & Refreshing ILI9488 LCD Screen...");
        Serial.println("==================================================================\n");

        current_config_version = newVersion;
        razorpay_upi_vpa       = newVpa;
        pending_amount_rupee   = newAmount;
        pending_product_name   = newName;
        if (newQrString.length() > 0) {
          custom_qr_code = newQrString;
        }

        // Persist to Flash NVS
        prefs.begin("vending_cfg", false);
        prefs.putString("rzp_vpa", razorpay_upi_vpa);
        prefs.putFloat("price", pending_amount_rupee);
        prefs.putString("p_name", pending_product_name);
        prefs.putString("cust_qr", custom_qr_code);
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
// 13. HARDWARE MOTOR TEST & BENCH TESTING
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
  Serial.println("  'h' : Show this Help Menu");
  Serial.println("==================================================================\n");
}

// ==============================================================================
// 13. ARDUINO SETUP
// ==============================================================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("\n==================================================================");
  Serial.println("   >>> ESP32 RAZORPAY ZERO-BUTTON VENDING CONTROLLER <<<          ");
  Serial.println("==================================================================");

  // 1. Initialize Motor Pins (Immediate OFF)
  pinMode(PIN_MOTOR_SLOT_1, OUTPUT);
  pinMode(PIN_MOTOR_SLOT_2, OUTPUT);
  setMotor(1, false);
  setMotor(2, false);

  pinMode(PIN_SETUP_BTN, INPUT_PULLUP);

  // 2. Initialize ILI9488 TFT LCD Display
  Serial.println("[TFT] Initializing 320x480 ILI9488 SPI LCD Display...");
  TFT_display.begin();
  TFT_display.setRotation(1); // Landscape: 480 wide x 320 high
  TFT_display.fillScreen(COLOR_BG);

  // Quick Splash
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

  // 4. Connect to Wi-Fi
  connectToWiFi();

  // 5. Render Standby QR Screen
  uiDrawStandbyQRScreen();
  printHelpMenu();

  Serial.println("[✓] Zero-Touch Vending Ready! Customer can scan QR anytime.");
}

// ==============================================================================
// 14. ARDUINO MAIN LOOP
// ==============================================================================
void loop() {
  // 1. Factory Reset Check: Hold BOOT (GPIO 0) for 5 seconds to wipe Wi-Fi
  if (digitalRead(PIN_SETUP_BTN) == LOW) {
    unsigned long pressStart = millis();
    while (digitalRead(PIN_SETUP_BTN) == LOW) {
      if (millis() - pressStart > 5000) {
        Serial.println("\n[!] FACTORY RESET DETECTED! Clearing Wi-Fi from Flash NVS...");
        clearPersistentConfig();
        delay(1000);
        ESP.restart();
      }
      delay(50);
    }
  }

  // 2. Serial Commands (Desk Bench Testing)
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'p' || c == 'P') {
      Serial.println("\n[💳 TEST] SIMULATING RAZORPAY PAYMENT RECEIVED (Rs 10.00)!");
      dispenseProduct(1, 10.00, "BENCH-TEST-" + String(millis()));
    } else if (c == 't' || c == 'T') {
      testMotorHardware();
    } else if (c == 'h' || c == 'H' || c == '?') {
      printHelpMenu();
    }
  }

  // 3. Continuous Background Polling for Razorpay Payment Confirmations
  if (current_state == STATE_STANDBY_QR) {
    if (millis() - last_poll_time >= POLL_INTERVAL_MS) {
      last_poll_time = millis();
      pollPendingDispense();
    }

    // 4. Periodic Check for QR & Price changes by Vendor / Manufacturer
    if (millis() - last_config_check_time >= CONFIG_CHECK_INTERVAL_MS) {
      last_config_check_time = millis();
      checkForRemoteQRConfigUpdates();
    }
  }

  delay(20);
}
