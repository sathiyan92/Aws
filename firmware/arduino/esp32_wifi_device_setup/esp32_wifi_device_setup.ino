/**
 * ==============================================================================
 * PROGRAM 1: ESP32 WI-FI & HARDWARE MAC / DEVICE ID PROVISIONER
 * ==============================================================================
 * Multi-Tenant IoT Fleet Platform
 * Target Board: ESP32 / ESP32-S3 (Arduino IDE)
 * 
 * Purpose:
 *   Dedicated hardware provisioning program for factory technicians and vendors:
 *   1. Displays ESP32 Hardware MAC Address and Silicon Chip ID for easy portal registration.
 *   2. Sets Wi-Fi credentials (SSID & Password) and Device ID (e.g., VM-000001).
 *   3. Stores all settings permanently in Flash NVS (Preferences.h) so they survive
 *      all reboots and firmware changes.
 *   4. Offers two configuration methods:
 *        A) Captive Web Portal: Connect phone/PC to "ESP32-WiFi-Setup" AP -> http://192.168.4.1
 *        B) Interactive Serial Monitor CLI (115200 baud).
 *   5. Validates network connectivity and cloud gateway ping.
 * 
 * Once this program saves the settings into Flash NVS, you can flash PROGRAM 2
 * (esp32_vending_qr_node.ino), which will immediately connect to your Wi-Fi!
 * ==============================================================================
 */

#include <WiFi.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <Preferences.h>
#include <HTTPClient.h>

// ------------------------------------------------------------------------------
// OPTIONAL: Quick Manual Hardcoded Defaults for Bench Testing
// (Leave empty to configure via Captive Portal or Serial CLI)
// ------------------------------------------------------------------------------
const char* DEFAULT_WIFI_SSID = "";        // e.g. "MyOfficeWiFi"
const char* DEFAULT_WIFI_PASS = "";        // e.g. "SecretPassword123"
const char* DEFAULT_DEVICE_ID = "VM-000001";
const char* DEFAULT_SERVER_URL = "http://35.154.219.82:8000";

const int PIN_STATUS_LED = 2; // Built-in LED on GPIO 2
const int PIN_BOOT_BTN   = 0; // Built-in BOOT button on GPIO 0

// NVS Configuration Storage
Preferences prefs;
String saved_ssid       = "";
String saved_pass       = "";
String saved_device_id  = "";
String saved_server_url = "";

// Web Server & DNS for AP Setup Mode
WebServer server(80);
DNSServer dnsServer;
bool in_ap_mode = false;

// ------------------------------------------------------------------------------
// CAPTIVE PORTAL HTML INTERFACE
// ------------------------------------------------------------------------------
const char SETUP_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ESP32 Wi-Fi & Device Setup</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0b1120; color: #f8fafc; padding: 20px; margin: 0; }
    .card { background: #1e293b; max-width: 440px; margin: 20px auto; padding: 25px; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); border: 1px solid #334155; }
    h2 { color: #38bdf8; margin: 0 0 6px 0; font-size: 1.3rem; }
    p { color: #94a3b8; font-size: 0.85rem; line-height: 1.4; margin-top: 0; }
    .info-box { background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 12px; margin-bottom: 16px; font-size: 0.8rem; }
    .info-row { display: flex; justify-content: space-between; margin-bottom: 4px; }
    .info-label { color: #64748b; }
    .info-val { color: #38bdf8; font-family: monospace; font-weight: bold; }
    label { display: block; font-size: 0.75rem; font-weight: 600; color: #cbd5e1; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
    input { width: 100%; padding: 11px; margin-bottom: 14px; border: 1px solid #334155; border-radius: 6px; background: #0f172a; color: #fff; font-size: 0.95rem; }
    input:focus { border-color: #38bdf8; outline: none; }
    button { width: 100%; padding: 13px; background: #0284c7; color: white; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; font-size: 1rem; transition: background 0.2s; }
    button:hover { background: #0369a1; }
    .note { font-size: 0.72rem; color: #64748b; margin-top: 14px; text-align: center; }
  </style>
</head>
<body>
  <div class="card">
    <h2>⚡ ESP32 Hardware Setup</h2>
    <p>Configure device Wi-Fi credentials and Device ID. Stored permanently in Flash NVS.</p>
    
    <div class="info-box">
      <div class="info-row">
        <span class="info-label">MAC Address:</span>
        <span class="info-val">%MAC_ADDRESS%</span>
      </div>
      <div class="info-row">
        <span class="info-label">Chip Silicon ID:</span>
        <span class="info-val">%CHIP_ID%</span>
      </div>
    </div>

    <form action="/save" method="POST">
      <label>Wi-Fi Network Name (SSID)</label>
      <input type="text" name="ssid" placeholder="e.g. Office_WiFi" value="%SAVED_SSID%" required>

      <label>Wi-Fi Password</label>
      <input type="password" name="pass" placeholder="Enter Wi-Fi password" required>

      <label>Device ID (Assigned in Portal)</label>
      <input type="text" name="dev_id" placeholder="e.g. VM-000001" value="%SAVED_DEV_ID%" required>

      <label>Cloud Server Base URL</label>
      <input type="text" name="srv_url" placeholder="http://35.154.219.82:8000" value="%SAVED_SRV_URL%" required>

      <button type="submit">💾 Save to Flash NVS & Connect</button>
    </form>

    <div class="note">Settings survive all reboots and subsequent firmware flashes!</div>
  </div>
</body>
</html>
)rawliteral";

// ------------------------------------------------------------------------------
// FLASH NVS STORAGE HELPERS
// ------------------------------------------------------------------------------
void loadConfigFromNVS() {
  prefs.begin("vending_cfg", false);
  saved_ssid       = prefs.getString("ssid", DEFAULT_WIFI_SSID);
  saved_pass       = prefs.getString("pass", DEFAULT_WIFI_PASS);
  saved_device_id  = prefs.getString("dev_id", DEFAULT_DEVICE_ID);
  saved_server_url = prefs.getString("srv_url", DEFAULT_SERVER_URL);
  prefs.end();
}

void saveConfigToNVS(String ssid, String pass, String dev_id, String srv_url) {
  prefs.begin("vending_cfg", false);
  prefs.putString("ssid", ssid);
  prefs.putString("pass", pass);
  prefs.putString("dev_id", dev_id);
  prefs.putString("token", "dev_token_" + dev_id);
  prefs.putString("srv_url", srv_url);
  prefs.end();

  saved_ssid = ssid;
  saved_pass = pass;
  saved_device_id = dev_id;
  saved_server_url = srv_url;

  Serial.println("\n[✓] Settings committed to Flash NVS (Preferences.h namespace: vending_cfg):");
  Serial.printf("    SSID      : %s\n", ssid.c_str());
  Serial.printf("    Device ID : %s\n", dev_id.c_str());
  Serial.printf("    Server URL: %s\n", srv_url.c_str());
}

void printHardwareInfo() {
  String mac = WiFi.macAddress();
  String chipId = "ESP32-CHIP-" + String((uint32_t)ESP.getEfuseMac(), HEX);

  Serial.println("\n==================================================================");
  Serial.println("  >>> ⚡ ESP32 HARDWARE IDENTIFICATION & PROVISIONING UTILITY <<<  ");
  Serial.println("==================================================================");
  Serial.print("  📡 Hardware MAC Address : "); Serial.println(mac);
  Serial.print("  🔬 Silicon Chip ID      : "); Serial.println(chipId);
  Serial.print("  🏷️  Current Device ID   : "); Serial.println(saved_device_id.length() > 0 ? saved_device_id : "(None)");
  Serial.print("  📶 Target Wi-Fi SSID    : "); Serial.println(saved_ssid.length() > 0 ? saved_ssid : "(Not Configured)");
  Serial.print("  🌐 Cloud Server URL     : "); Serial.println(saved_server_url);
  Serial.println("------------------------------------------------------------------");
  Serial.println("  📋 COPY THIS MAC FOR PORTAL REGISTRATION:");
  Serial.printf("     Mac: %s\n", mac.c_str());
  Serial.println("==================================================================\n");
}

// ------------------------------------------------------------------------------
// CAPTIVE WEB SERVER HANDLERS
// ------------------------------------------------------------------------------
void handleWebRoot() {
  String mac = WiFi.macAddress();
  String chipId = "ESP32-CHIP-" + String((uint32_t)ESP.getEfuseMac(), HEX);

  String html = SETUP_HTML;
  html.replace("%MAC_ADDRESS%", mac);
  html.replace("%CHIP_ID%", chipId);
  html.replace("%SAVED_SSID%", saved_ssid);
  html.replace("%SAVED_DEV_ID%", saved_device_id);
  html.replace("%SAVED_SRV_URL%", saved_server_url);

  server.send(200, "text/html", html);
}

void handleWebSave() {
  String new_ssid = server.arg("ssid");
  String new_pass = server.arg("pass");
  String new_dev  = server.arg("dev_id");
  String new_srv  = server.arg("srv_url");

  saveConfigToNVS(new_ssid, new_pass, new_dev, new_srv);

  String resp = "<html><body style='background:#0b1120;color:#38bdf8;text-align:center;padding:40px;font-family:sans-serif;'>";
  resp += "<h2>✓ Configuration Saved to Flash NVS!</h2>";
  resp += "<p style='color:#94a3b8;'>Rebooting and connecting to " + new_ssid + "...</p>";
  resp += "<p style='color:#64748b;'>You can now flash the Vending Machine QR Code program!</p></body></html>";
  server.send(200, "text/html", resp);

  delay(2000);
  ESP.restart();
}

void startSetupAP() {
  in_ap_mode = true;
  WiFi.disconnect();
  WiFi.mode(WIFI_AP);

  String ap_name = "ESP32-WiFi-Setup";
  WiFi.softAP(ap_name.c_str());

  dnsServer.start(53, "*", WiFi.softAPIP());
  server.on("/", handleWebRoot);
  server.on("/save", HTTP_POST, handleWebSave);
  server.onNotFound(handleWebRoot);
  server.begin();

  Serial.println("\n------------------------------------------------------------------");
  Serial.println("  📶 ACCESS POINT STARTED FOR CONFIGURATION:");
  Serial.printf("     1. Connect your phone/laptop to Wi-Fi: %s\n", ap_name.c_str());
  Serial.println("     2. Open browser at: http://192.168.4.1");
  Serial.println("     3. Enter Wi-Fi Name, Password & Device ID, then click Save!");
  Serial.println("------------------------------------------------------------------\n");
}

// ------------------------------------------------------------------------------
// TEST CONNECTION & CLOUD PING
// ------------------------------------------------------------------------------
bool testConnection() {
  if (saved_ssid.length() == 0) return false;

  Serial.printf("[Wi-Fi] Attempting connection to: %s\n", saved_ssid.c_str());
  WiFi.mode(WIFI_STA);
  WiFi.begin(saved_ssid.c_str(), saved_pass.c_str());

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
    Serial.print("    Assigned IP : "); Serial.println(WiFi.localIP());
    Serial.print("    Signal RSSI : "); Serial.print(WiFi.RSSI()); Serial.println(" dBm");

    // Ping cloud gateway health check
    HTTPClient http;
    WiFiClient client;
    String pingUrl = saved_server_url + "/docs";
    Serial.printf("[Cloud] Testing cloud server reachability (%s)...\n", saved_server_url.c_str());
    http.setConnectTimeout(6000);
    http.setTimeout(6000);
    if (http.begin(client, pingUrl)) {
      int code = http.GET();
      if (code == 200 || code == 307 || code == 404) {
        Serial.printf("[✓] Cloud Server Reachable! (HTTP Response: %d)\n", code);
      } else {
        Serial.printf("[!] Server returned HTTP %d\n", code);
      }
      http.end();
    }
    return true;
  } else {
    Serial.println("\n[✗] Could not connect to target Wi-Fi with stored credentials.");
    return false;
  }
}

// ------------------------------------------------------------------------------
// ARDUINO SETUP & LOOP
// ------------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(1200);

  pinMode(PIN_STATUS_LED, OUTPUT);
  pinMode(PIN_BOOT_BTN, INPUT_PULLUP);
  digitalWrite(PIN_STATUS_LED, LOW);

  // Load saved credentials from NVS
  loadConfigFromNVS();

  // Print hardware identification (MAC, Chip ID, current config)
  printHardwareInfo();

  // Attempt connection with saved credentials
  bool connected = testConnection();

  if (!connected) {
    // If no credentials or connection failed, start Setup AP & Captive Portal
    startSetupAP();
  } else {
    Serial.println("\n==================================================================");
    Serial.println("  🎉 SETUP VERIFIED! READY FOR VENDING PROGRAM!");
    Serial.println("  Your ESP32 is online and its settings are committed to Flash NVS.");
    Serial.println("  You can now open and flash 'esp32_vending_qr_node.ino'!");
    Serial.println("  (Hold BOOT button GPIO 0 for 5 seconds anytime to reconfigure Wi-Fi)");
    Serial.println("==================================================================\n");
  }
}

void loop() {
  // If in AP Setup mode, process DNS and HTTP clients
  if (in_ap_mode) {
    dnsServer.processNextRequest();
    server.handleClient();
    digitalWrite(PIN_STATUS_LED, (millis() / 250) % 2); // Blink rapidly
  }

  // Hold BOOT button for 5s to trigger factory reset & start AP mode
  if (digitalRead(PIN_BOOT_BTN) == LOW) {
    unsigned long pressStart = millis();
    while (digitalRead(PIN_BOOT_BTN) == LOW) {
      if (millis() - pressStart > 5000) {
        Serial.println("\n[!] FACTORY RESET TRIGGERED! Wiping credentials and starting AP...");
        prefs.begin("vending_cfg", false);
        prefs.clear();
        prefs.end();
        startSetupAP();
        break;
      }
      delay(50);
    }
  }

  // Interactive Serial CLI: Type "SETUP" in Serial Monitor to re-enter AP mode
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.equalsIgnoreCase("SETUP") || cmd.equalsIgnoreCase("WIFI")) {
      Serial.println("\n[CLI] Starting AP Setup Mode via Serial request...");
      startSetupAP();
    } else if (cmd.equalsIgnoreCase("INFO") || cmd.equalsIgnoreCase("MAC")) {
      printHardwareInfo();
    }
  }

  delay(20);
}
