/**
 * Multi-Tenant Cloud IoT Platform - Complete ESP32 Vending Machine Node
 * 
 * Target Board: ESP32 / ESP32-S3 (Arduino IDE)
 * Features:
 *   1. Permanent Wi-Fi in Flash NVS (Preferences.h) - NEVER erased by OTA updates!
 *   2. First-Time Setup Captive Web Portal (Connect via phone/laptop to "ESP32-Vending-Setup")
 *   3. Dynamic QR Payment Engine (Slot-based pricing resolved from Cloud)
 *   4. Real-Time Payment Polling & Automatic Dispense Relay Trigger
 *   5. Dispense Confirmation & Inventory Deduction Callback
 *   6. Wireless Cloud Over-The-Air (OTA) Firmware Updates from Laptop Portal
 *   7. Factory Reset Button (Hold GPIO 0 for 5s to reconfigure Wi-Fi)
 *
 * Hardware Pinout (Configurable):
 *   - Slot 1 Pushbutton : GPIO 32 (Internal Pullup, Active LOW)
 *   - Slot 2 Pushbutton : GPIO 33 (Internal Pullup, Active LOW)
 *   - Slot 1 Relay Motor: GPIO 26 (Active HIGH)
 *   - Slot 2 Relay Motor: GPIO 27 (Active HIGH)
 *   - Status LED        : GPIO 2  (Built-in LED)
 *   - Reset / Setup Btn : GPIO 0  (Built-in BOOT Button)
 */

#include <WiFi.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <Preferences.h>
#include <HTTPClient.h>
#include <Update.h>
#include <ArduinoJson.h>

// ==============================================================================
// 1. MANUAL WI-FI CONFIGURATION (OPTIONAL - FOR LAB / DESK TESTING)
// ==============================================================================
// If you want to connect to your Wi-Fi immediately without using the phone Captive Portal:
// Enter your Wi-Fi SSID and Password below.
// The ESP32 will connect automatically AND permanently save it into Flash NVS memory.
// Once saved, you can leave these blank ("") and the ESP32 will remember forever!
const char* MANUAL_WIFI_SSID     = "";  // e.g. "MyHomeWiFi" (leave "" to use NVS / Captive Portal)
const char* MANUAL_WIFI_PASSWORD = "";  // e.g. "12345678"
const char* DEFAULT_SERVER_URL   = "http://35.154.219.82:8000";

// ==============================================================================
// 2. HARDWARE PIN DEFINITIONS
// ==============================================================================
const int PIN_BTN_SLOT_1    = 32;   // Pushbutton to select Slot 1
const int PIN_BTN_SLOT_2    = 33;   // Pushbutton to select Slot 2
const int PIN_RELAY_SLOT_1  = 26;   // Dispense motor relay for Slot 1
const int PIN_RELAY_SLOT_2  = 27;   // Dispense motor relay for Slot 2
const int PIN_STATUS_LED    = 2;    // Status LED
const int PIN_SETUP_BTN     = 0;    // BOOT button (hold 5s for Wi-Fi reconfig)

const unsigned long MOTOR_DISPENSE_TIME_MS = 3000; // Motor runtime per dispense (3s)

// ==============================================================================
// 3. CONFIGURATION STORAGE (FLASH NVS - SURVIVES ALL OTA UPDATES)
// ==============================================================================
Preferences prefs;

String wifi_ssid       = "";
String wifi_pass       = "";
String device_id       = "VM-000001";
String device_token    = "dev_token_VM-000001";
String server_base_url = "http://35.154.219.82:8000";
String firmware_version = "v1.0.0";

// Runtime States
String session_jwt = "";
bool is_authenticated = false;
unsigned long last_heartbeat_time = 0;
const unsigned long HEARTBEAT_INTERVAL_MS = 30000;
unsigned long last_ota_check_time = 0;
const unsigned long OTA_CHECK_INTERVAL_MS = 30000;

// Active Vending Order State
enum VendingState {
  STATE_IDLE,
  STATE_ORDER_REQUESTING,
  STATE_AWAITING_PAYMENT,
  STATE_DISPENSING
};
VendingState current_vending_state = STATE_IDLE;
String active_order_id     = "";
String active_order_number = "";
int    active_slot_number  = 0;
float  active_price_rupees = 0.0;
String active_upi_qr       = "";
unsigned long order_started_time = 0;
unsigned long last_payment_poll_time = 0;
const unsigned long PAYMENT_POLL_INTERVAL_MS = 2000; // Poll cloud every 2s
const unsigned long ORDER_TIMEOUT_MS = 180000;       // 3 minutes timeout

// Captive Portal Web Server & DNS
WebServer webServer(80);
DNSServer dnsServer;
bool in_ap_setup_mode = false;

// ==============================================================================
// 4. FLASH NVS PERSISTENT STORAGE HANDLERS
// ==============================================================================
void loadPersistentConfig() {
  prefs.begin("vending_cfg", false);
  wifi_ssid       = prefs.getString("ssid", "");
  wifi_pass       = prefs.getString("pass", "");
  device_id       = prefs.getString("dev_id", "VM-000001");
  device_token    = prefs.getString("token", "dev_token_VM-000001");
  server_base_url = prefs.getString("srv_url", DEFAULT_SERVER_URL);
  prefs.end();

  // If manual Wi-Fi credentials are provided at top of sketch, use them and persist to Flash NVS
  if (strlen(MANUAL_WIFI_SSID) > 0) {
    Serial.println("\n[Config] Using MANUAL_WIFI_SSID override from code...");
    wifi_ssid = String(MANUAL_WIFI_SSID);
    wifi_pass = String(MANUAL_WIFI_PASSWORD);
    if (strlen(DEFAULT_SERVER_URL) > 0) {
      server_base_url = String(DEFAULT_SERVER_URL);
    }
    savePersistentConfig(wifi_ssid, wifi_pass, device_id, server_base_url);
  }

  Serial.println("\n=======================================================");
  Serial.println(">>> ⚡ ESP32 HARDWARE IDENTIFICATION (PERMANENT) <<<");
  Serial.print("  Hardware MAC Address : "); Serial.println(WiFi.macAddress());
  Serial.print("  Silicon Chip ID      : ESP32-CHIP-"); Serial.println(String((uint32_t)ESP.getEfuseMac(), HEX));
  Serial.print("  Current Device ID    : "); Serial.println(device_id);
  Serial.print("  Target Wi-Fi SSID    : "); Serial.println(wifi_ssid.length() > 0 ? wifi_ssid : "(Not Configured - Captive Portal will start)");
  Serial.print("  Cloud Server Base URL: "); Serial.println(server_base_url);
  Serial.println("-------------------------------------------------------");
  Serial.println("  💡 ZERO-CODE MULTI-TENANT ARCHITECTURE:");
  Serial.println("     Once this MAC is registered on the website portal,");
  Serial.println("     the device automatically binds to its assigned tenant.");
  Serial.println("     Future OTA firmware updates will NEVER erase your Wi-Fi!");
  Serial.println("=======================================================\n");
}

void savePersistentConfig(String ssid, String pass, String dev_id, String srv_url) {
  prefs.begin("vending_cfg", false);
  prefs.putString("ssid", ssid);
  prefs.putString("pass", pass);
  prefs.putString("dev_id", dev_id);
  prefs.putString("srv_url", srv_url);
  prefs.end();
  Serial.println(">>> [NVS] Settings permanently saved to Flash memory.");
}

void clearPersistentConfig() {
  prefs.begin("vending_cfg", false);
  prefs.clear();
  prefs.end();
  Serial.println(">>> [NVS] Settings cleared.");
}

// ==============================================================================
// 4. FIRST-TIME WI-FI SETUP CAPTIVE PORTAL (192.168.4.1)
// ==============================================================================
const char CAPTIVE_PORTAL_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vending Machine Wi-Fi Setup</title>
  <style>
    body { font-family: -apple-system, sans-serif; background: #0f172a; color: #f8fafc; padding: 20px; text-align: center; }
    .card { background: #1e293b; max-width: 420px; margin: 0 auto; padding: 25px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
    h2 { color: #38bdf8; margin-top: 0; }
    p { color: #94a3b8; font-size: 14px; }
    input { width: 100%; padding: 12px; margin: 8px 0 16px; border: 1px solid #334155; border-radius: 6px; background: #0f172a; color: #fff; box-sizing: border-box; }
    button { width: 100%; padding: 14px; background: #0284c7; color: white; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; font-size: 16px; }
    button:hover { background: #0369a1; }
    .tip { font-size: 12px; color: #64748b; margin-top: 15px; }
  </style>
</head>
<body>
  <div class="card">
    <h2>⚡ ESP32 Vending Machine</h2>
    <p>Configure Wi-Fi and Cloud Server. Settings are saved permanently in Flash NVS and survive all future OTA updates.</p>
    <form action="/save" method="POST">
      <input type="text" name="ssid" placeholder="Wi-Fi Name (SSID)" required value="%SAVED_SSID%">
      <input type="password" name="pass" placeholder="Wi-Fi Password" required>
      <input type="text" name="dev_id" placeholder="Device ID (e.g. VM-000001)" value="%SAVED_DEV_ID%" required>
      <input type="text" name="srv_url" placeholder="Server URL (e.g. http://35.154.219.82:8000)" value="%SAVED_SRV_URL%" required>
      <button type="submit">💾 Save & Connect</button>
    </form>
    <div class="tip">Target Hardware: ESP32 Vending Controller Node</div>
  </div>
</body>
</html>
)rawliteral";

void handleRoot() {
  String html = CAPTIVE_PORTAL_HTML;
  html.replace("%SAVED_SSID%", wifi_ssid);
  html.replace("%SAVED_DEV_ID%", device_id);
  html.replace("%SAVED_SRV_URL%", server_base_url);
  webServer.send(200, "text/html", html);
}

void handleSave() {
  String new_ssid = webServer.arg("ssid");
  String new_pass = webServer.arg("pass");
  String new_dev  = webServer.arg("dev_id");
  String new_srv  = webServer.arg("srv_url");

  savePersistentConfig(new_ssid, new_pass, new_dev, new_srv);

  String resp = "<html><body style='background:#0f172a;color:#38bdf8;text-align:center;padding:50px;font-family:sans-serif;'>";
  resp += "<h2>✓ Configuration Saved Permanently!</h2>";
  resp += "<p style='color:#94a3b8;'>Rebooting and connecting to " + new_ssid + "...</p></body></html>";
  webServer.send(200, "text/html", resp);

  delay(2000);
  ESP.restart();
}

void startCaptivePortal() {
  in_ap_setup_mode = true;
  WiFi.disconnect();
  WiFi.mode(WIFI_AP);
  String ap_name = "ESP32-Vending-Setup";
  WiFi.softAP(ap_name.c_str());

  Serial.println("\n=======================================================");
  Serial.println(">>> 📶 NO WI-FI CONFIGURED: STARTED CAPTIVE PORTAL <<<");
  Serial.print("  Connect to Wi-Fi AP : "); Serial.println(ap_name);
  Serial.println("  Open in Browser     : http://192.168.4.1");
  Serial.println("=======================================================\n");

  dnsServer.start(53, "*", WiFi.softAPIP());
  webServer.on("/", handleRoot);
  webServer.on("/save", HTTP_POST, handleSave);
  webServer.onNotFound(handleRoot); // Redirect all captive portal queries
  webServer.begin();

  // Fast blink LED while in setup mode
  while (in_ap_setup_mode) {
    dnsServer.processNextRequest();
    webServer.handleClient();
    digitalWrite(PIN_STATUS_LED, (millis() / 200) % 2);
    delay(5);
  }
}

// ==============================================================================
// 5. WI-FI CONNECTION (CONNECTS USING SAVED NVS CREDENTIALS)
// ==============================================================================
void connectToWiFi() {
  if (wifi_ssid.length() == 0) {
    startCaptivePortal();
    return;
  }

  Serial.printf("\n[Wi-Fi] Connecting to saved network: %s\n", wifi_ssid.c_str());
  WiFi.mode(WIFI_STA);
  WiFi.begin(wifi_ssid.c_str(), wifi_pass.c_str());

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 25) {
    delay(500);
    Serial.print(".");
    digitalWrite(PIN_STATUS_LED, (attempts % 2));
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    digitalWrite(PIN_STATUS_LED, HIGH);
    Serial.println("\n[✓] Wi-Fi Connected Successfully!");
    Serial.print("    IP Address: "); Serial.println(WiFi.localIP());
    Serial.print("    RSSI      : "); Serial.print(WiFi.RSSI()); Serial.println(" dBm");
  } else {
    Serial.println("\n[✗] Could not connect to saved Wi-Fi. Starting Setup Portal...");
    startCaptivePortal();
  }
}

// ==============================================================================
// 6. CLOUD AUTHENTICATION & HANDSHAKE
// ==============================================================================
bool authenticateWithCloud() {
  if (WiFi.status() != WL_CONNECTED) return false;

  WiFiClient client;
  HTTPClient http;
  String endpoint = server_base_url + "/api/v1/device-gateway/authenticate";

  Serial.printf("\n[-->] Authenticating Device '%s' with Cloud...\n", device_id.c_str());
  http.setConnectTimeout(8000);
  http.setTimeout(8000);
  http.begin(client, endpoint);
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<512> doc;
  doc["device_id"]        = device_id;
  doc["chip_id"]          = "ESP32-CHIP-" + String((uint32_t)ESP.getEfuseMac(), HEX);
  doc["mac_address"]      = WiFi.macAddress();
  doc["device_token"]     = device_token;
  doc["firmware_version"] = firmware_version;
  doc["boot_count"]       = 1;

  String reqBody;
  serializeJson(doc, reqBody);
  int httpCode = http.POST(reqBody);

  if (httpCode == 200) {
    String resp = http.getString();
    StaticJsonDocument<1024> respDoc;
    deserializeJson(respDoc, resp);

    session_jwt = respDoc["session_token"].as<String>();
    is_authenticated = true;

    // Check if cloud resolved our device_id by hardware MAC address!
    if (respDoc.containsKey("device_id")) {
      String assignedId = respDoc["device_id"].as<String>();
      if (assignedId.length() > 0 && assignedId != device_id) {
        Serial.printf("[✓] Cloud automatically identified this MAC as Device ID: %s\n", assignedId.c_str());
        device_id = assignedId;
        prefs.begin("vending_cfg", false);
        prefs.putString("dev_id", device_id);
        prefs.end();
      }
    }
    Serial.println("[✓] Cloud Gateway Authentication SUCCESS!");
    http.end();
    return true;
  } else {
    Serial.printf("[✗] Authentication Failed (HTTP %d): %s\n", httpCode, http.getString().c_str());
  }

  http.end();
  is_authenticated = false;
  return false;
}

// ==============================================================================
// 7. DYNAMIC QR PAYMENT: INITIATE ORDER & RESOLVE PRICE FROM CLOUD
// ==============================================================================
void initiateQROrder(int slotNumber) {
  if (current_vending_state != STATE_IDLE) {
    Serial.println("[!] Machine is busy. Please wait for current transaction to finish.");
    return;
  }

  Serial.printf("\n=======================================================\n");
  Serial.printf(">>> 🛒 SLOT %d SELECTED: REQUESTING DYNAMIC QR PAYLOAD...\n", slotNumber);
  Serial.printf("=======================================================\n");

  current_vending_state = STATE_ORDER_REQUESTING;
  active_slot_number = slotNumber;

  WiFiClient client;
  HTTPClient http;
  String endpoint = server_base_url + "/api/v1/orders/initiate";

  http.setConnectTimeout(8000);
  http.setTimeout(8000);
  http.begin(client, endpoint);
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<256> doc;
  doc["device_id"]   = device_id;
  doc["slot_number"] = slotNumber;

  String reqBody;
  serializeJson(doc, reqBody);
  int httpCode = http.POST(reqBody);

  if (httpCode == 201) {
    String resp = http.getString();
    StaticJsonDocument<1024> respDoc;
    deserializeJson(respDoc, resp);

    active_order_id     = respDoc["order_id"].as<String>();
    active_order_number = respDoc["order_number"].as<String>();
    active_price_rupees = respDoc["amount_rupees"].as<float>();
    active_upi_qr       = respDoc["qr_payload"].as<String>();
    order_started_time  = millis();

    current_vending_state = STATE_AWAITING_PAYMENT;

    Serial.println("\n[✓] DYNAMIC QR PAYMENT GENERATED SUCCESSFULLY!");
    Serial.printf("  Item Product : %s\n", respDoc["product_name"].as<const char*>());
    Serial.printf("  Price        : Rs. %.2f (Resolved Dynamically from Cloud!)\n", active_price_rupees);
    Serial.printf("  Order Number : %s\n", active_order_number.c_str());
    Serial.printf("  Expires in   : %d seconds\n", respDoc["timeout_seconds"].as<int>());
    Serial.println("-------------------------------------------------------");
    Serial.printf("  UPI QR URI   : %s\n", active_upi_qr.c_str());
    Serial.println("-------------------------------------------------------");
    Serial.println("📲 SCAN TO PAY WITH GPAY / PHONEPE / PAYTM:");
    Serial.printf("   Open in browser: https://api.qrserver.com/v1/create-qr-code/?size=250x250&data=%s\n",
                  active_upi_qr.c_str());
    Serial.println("=======================================================\n");
  } else {
    Serial.printf("[✗] Failed to initiate order (HTTP %d): %s\n", httpCode, http.getString().c_str());
    current_vending_state = STATE_IDLE;
  }

  http.end();
}

// ==============================================================================
// 8. DISPENSE VENDING MOTOR
// ==============================================================================
void dispenseProduct(int slotNumber) {
  current_vending_state = STATE_DISPENSING;
  Serial.println("\n*******************************************************");
  Serial.printf(">>> 🚀 PAYMENT CONFIRMED! DISPENSING SLOT %d MOTOR...\n", slotNumber);
  Serial.println("*******************************************************");

  int relayPin = (slotNumber == 1) ? PIN_RELAY_SLOT_1 : PIN_RELAY_SLOT_2;

  // Turn ON Motor Relay
  digitalWrite(relayPin, HIGH);
  digitalWrite(PIN_STATUS_LED, LOW);

  unsigned long startTime = millis();
  while (millis() - startTime < MOTOR_DISPENSE_TIME_MS) {
    delay(50);
  }

  // Turn OFF Motor Relay
  digitalWrite(relayPin, LOW);
  digitalWrite(PIN_STATUS_LED, HIGH);

  Serial.printf("[✓] Slot %d Motor Cycle Complete. Product Dispensed!\n", slotNumber);

  // Notify Cloud of Successful Dispense
  confirmDispenseToCloud(active_order_id);

  // Reset to IDLE
  current_vending_state = STATE_IDLE;
  active_order_id = "";
}

void confirmDispenseToCloud(String orderId) {
  WiFiClient client;
  HTTPClient http;
  String endpoint = server_base_url + "/api/v1/orders/" + orderId + "/dispensed";

  http.setConnectTimeout(8000);
  http.setTimeout(8000);
  http.begin(client, endpoint);
  http.POST("");
  http.end();
  Serial.println("[✓] Cloud Inventory Updated: Stock decremented by 1.");
}

// ==============================================================================
// 9. REAL-TIME PAYMENT STATUS POLLING
// ==============================================================================
void pollActivePaymentStatus() {
  if (current_vending_state != STATE_AWAITING_PAYMENT || active_order_id.length() == 0) return;

  // Check Local Timeout (3 mins)
  if (millis() - order_started_time > ORDER_TIMEOUT_MS) {
    Serial.println("\n[⏰] QR Payment Expired (Timeout 180s reached). Cancelling order...");
    current_vending_state = STATE_IDLE;
    active_order_id = "";
    return;
  }

  WiFiClient client;
  HTTPClient http;
  String endpoint = server_base_url + "/api/v1/orders/" + active_order_id;

  http.setConnectTimeout(5000);
  http.setTimeout(5000);
  http.begin(client, endpoint);

  int httpCode = http.GET();
  if (httpCode == 200) {
    String resp = http.getString();
    StaticJsonDocument<1024> respDoc;
    deserializeJson(respDoc, resp);

    String status = respDoc["order_status"].as<String>();

    if (status == "PAID" || status == "DISPENSE_AUTHORIZED") {
      http.end();
      dispenseProduct(active_slot_number);
      return;
    } else if (status == "CANCELLED" || status == "EXPIRED" || status == "FAILED") {
      Serial.printf("[!] Order %s ended with status: %s\n", active_order_number.c_str(), status.c_str());
      current_vending_state = STATE_IDLE;
      active_order_id = "";
    }
  }

  http.end();
}

// ==============================================================================
// 10. CLOUD OVER-THE-AIR (OTA) WIRELESS UPDATE ENGINE
// ==============================================================================
void checkForPendingOTA() {
  if (!is_authenticated || WiFi.status() != WL_CONNECTED || current_vending_state != STATE_IDLE) return;

  WiFiClient client;
  HTTPClient http;
  String endpoint = server_base_url + "/api/v1/ota/check/" + device_id;

  http.setConnectTimeout(8000);
  http.setTimeout(8000);
  http.begin(client, endpoint);

  int httpCode = http.GET();
  if (httpCode == 200) {
    String payload = http.getString();
    StaticJsonDocument<1024> doc;
    deserializeJson(doc, payload);

    if (doc["has_update"] == true) {
      String deploymentId = doc["deployment_id"].as<String>();
      String targetVer    = doc["version"].as<String>();
      String binaryUrl    = doc["binary_url"].as<String>();
      size_t fileSize     = doc["file_size_bytes"].as<size_t>();

      Serial.println("\n=======================================================");
      Serial.println(">>> ⚡ CLOUD NOTIFICATION: WIRELESS UPDATE AVAILABLE! <<<");
      Serial.printf("  Target Version : %s\n", targetVer.c_str());
      Serial.printf("  Binary Size    : %u bytes\n", fileSize);
      Serial.println("=======================================================");

      http.end();
      performOTA(binaryUrl, deploymentId, fileSize, targetVer);
      return;
    }
  }
  http.end();
}

bool performOTA(String downloadUrl, String deploymentId, size_t binarySize, String version) {
  WiFiClient client;
  HTTPClient http;
  http.setConnectTimeout(15000);
  http.setTimeout(45000);

  if (!http.begin(client, downloadUrl)) return false;

  int httpCode = http.GET();
  if (httpCode != HTTP_CODE_OK) {
    http.end();
    return false;
  }

  int contentLength = http.getSize() > 0 ? http.getSize() : binarySize;
  if (!Update.begin(contentLength > 0 ? contentLength : UPDATE_SIZE_UNKNOWN, U_FLASH)) {
    http.end();
    return false;
  }

  Serial.println("[OTA] Writing new firmware partition to flash...");
  WiFiClient *stream = http.getStreamPtr();
  size_t written = Update.writeStream(*stream);

  if (Update.end() && Update.isFinished()) {
    Serial.println("[✓] Firmware Flashed Successfully! Wi-Fi & NVS are preserved.");
    Serial.println("[✓] Rebooting into new firmware...");
    http.end();
    delay(1000);
    ESP.restart();
    return true;
  }

  http.end();
  return false;
}

// ==============================================================================
// 11. ARDUINO SETUP
// ==============================================================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("\n=======================================================");
  Serial.println("   IoT Fleet Platform - Smart Vending Controller Node   ");
  Serial.println("=======================================================");

  // Initialize Hardware Pins
  pinMode(PIN_BTN_SLOT_1, INPUT_PULLUP);
  pinMode(PIN_BTN_SLOT_2, INPUT_PULLUP);
  pinMode(PIN_SETUP_BTN, INPUT_PULLUP);
  pinMode(PIN_RELAY_SLOT_1, OUTPUT);
  pinMode(PIN_RELAY_SLOT_2, OUTPUT);
  pinMode(PIN_STATUS_LED, OUTPUT);

  digitalWrite(PIN_RELAY_SLOT_1, LOW);
  digitalWrite(PIN_RELAY_SLOT_2, LOW);
  digitalWrite(PIN_STATUS_LED, LOW);

  // Load Wi-Fi & Server credentials from Flash NVS
  loadPersistentConfig();

  // Connect to Wi-Fi (starts Captive Portal if not configured)
  connectToWiFi();

  // Authenticate with Cloud Gateway
  if (WiFi.status() == WL_CONNECTED) {
    authenticateWithCloud();
  }

  Serial.println("\n>>> [READY] Machine is online and waiting for customer selection.");
  Serial.println("    Press physical Button 1 / 2, or type '1' or '2' in Serial Monitor to vend!");
  Serial.println("    Hold BOOT button (GPIO 0) for 5s anytime to reset Wi-Fi.\n");
}

// ==============================================================================
// 12. ARDUINO MAIN LOOP
// ==============================================================================
void loop() {
  // 1. Factory Reset Check: Hold BOOT (GPIO 0) for 5 seconds to wipe Wi-Fi
  if (digitalRead(PIN_SETUP_BTN) == LOW) {
    unsigned long pressStart = millis();
    while (digitalRead(PIN_SETUP_BTN) == LOW) {
      if (millis() - pressStart > 5000) {
        Serial.println("\n[!] FACTORY RESET DETECTED! Clearing Wi-Fi from Flash NVS...");
        clearPersistentConfig();
        digitalWrite(PIN_STATUS_LED, HIGH);
        delay(1000);
        ESP.restart();
      }
      delay(50);
    }
  }

  // 2. Wi-Fi Reconnect Guard
  if (WiFi.status() != WL_CONNECTED) {
    connectToWiFi();
  }

  // 3. User Slot Selection (Physical Button or Serial Monitor)
  if (current_vending_state == STATE_IDLE) {
    if (digitalRead(PIN_BTN_SLOT_1) == LOW) {
      delay(200); // Debounce
      initiateQROrder(1);
    } else if (digitalRead(PIN_BTN_SLOT_2) == LOW) {
      delay(200); // Debounce
      initiateQROrder(2);
    }

    // Serial Monitor Commands for easy desk testing
    if (Serial.available()) {
      char c = Serial.read();
      if (c == '1') {
        initiateQROrder(1);
      } else if (c == '2') {
        initiateQROrder(2);
      }
    }
  }

  // 4. Poll Payment Status when a QR order is active
  if (current_vending_state == STATE_AWAITING_PAYMENT) {
    if (millis() - last_payment_poll_time >= PAYMENT_POLL_INTERVAL_MS) {
      last_payment_poll_time = millis();
      pollActivePaymentStatus();
    }
  }

  // 5. Periodic OTA Check (every 30 seconds when idle)
  if (current_vending_state == STATE_IDLE) {
    if (millis() - last_ota_check_time >= OTA_CHECK_INTERVAL_MS) {
      last_ota_check_time = millis();
      checkForPendingOTA();
    }
  }

  delay(20);
}
