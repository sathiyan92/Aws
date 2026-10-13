/**
 * Multi-Tenant Cloud IoT Platform - ESP32 Arduino Client
 *
 * Target Board: ESP32 / ESP32-S3 (Arduino IDE or PlatformIO)
 * Required Libraries:
 *   - WiFi (built-in)
 *   - HTTPClient (built-in)
 *   - ArduinoJson (Install via Arduino Library Manager, version 6.x or 7.x)
 *
 * Instructions:
 * 1. Set your local Wi-Fi credentials (WIFI_SSID & WIFI_PASS).
 * 2. Set your PC's Local LAN IP address (SERVER_HOST), e.g.
 * "192.168.1.50:8000". (Do NOT use "localhost" - the ESP32 needs your
 * computer's LAN IP).
 * 3. Set your Device ID and Provisioning Token from the Manufacturer Portal.
 * 4. Open Serial Monitor at 115200 baud to view handshake and heartbeats.
 */

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <Update.h>
#include <WiFi.h>

// ==============================================================================
// 1. NETWORK & SERVER CONFIGURATION
// ==============================================================================
const char *WIFI_SSID = "Airtel_Gomathi WIFI"; // <-- Put your Wi-Fi Name here
const char *WIFI_PASS = "Deva@0804"; // <-- Put your Wi-Fi Password here

// Local PC IP hosting the backend (e.g., http://192.168.1.50:8000)
// To find your IP on Windows: Open PowerShell and run 'ipconfig', look for IPv4
// Address.
const char *SERVER_BASE_URL = "http://192.168.1.3:8000";

// ==============================================================================
// 2. DEVICE IDENTITY CREDENTIALS
// ==============================================================================
// You can use a seeded machine (e.g. VM-000001) or register a new one in the
// portal. For VM-000001:
//   DEVICE_ID: "VM-000001"
//   DEVICE_TOKEN: "dev_token_VM-000001"
//   CHIP_ID: "ESP32-S3-0x3C8427F8B101"
//   MAC_ADDR: "3C:84:27:F8:B1:01"
//
// Or set USE_REAL_HARDWARE_ID = true to use your board's actual MAC & Chip ID!
bool USE_REAL_HARDWARE_ID = false;

String device_id = "VM-000001";
String device_token = "dev_token_VM-000001";
String chip_id = "ESP32-S3-0x3C8427F8B101";
String mac_address = "3C:84:27:F8:B1:01";

// Session & Firmware State
String current_firmware_version = "v1.0.0";
String session_jwt = "";
bool is_authenticated = false;
unsigned long last_heartbeat_time = 0;
const unsigned long HEARTBEAT_INTERVAL_MS = 30000; // Send heartbeat every 30 seconds
unsigned long last_ota_check_time = 0;
const unsigned long OTA_CHECK_INTERVAL_MS = 30000; // Check for pending OTA updates every 30 seconds

// ==============================================================================
// HELPER: READ HARDWARE SILICON IDENTIFIERS
// ==============================================================================
void readBoardHardwareIdentifiers() {
  // Read hardware MAC address
  String realMac = WiFi.macAddress();

  // Read eFuse 64-bit Chip ID
  uint64_t efuse = ESP.getEfuseMac();
  char chipBuf[32];
  snprintf(chipBuf, sizeof(chipBuf), "ESP32-CHIP-%04X%08X",
           (uint16_t)(efuse >> 32), (uint32_t)efuse);

  Serial.println("\n-------------------------------------------");
  Serial.println(">>> ESP32 PHYSICAL HARDWARE IDENTIFIERS <<<");
  Serial.print("  Board MAC Address : ");
  Serial.println(realMac);
  Serial.print("  eFuse Chip ID     : ");
  Serial.println(chipBuf);
  Serial.println("-------------------------------------------");
  Serial.println("Tip: Use these when registering in Manufacturer Portal!");
  Serial.println("-------------------------------------------\n");

  if (USE_REAL_HARDWARE_ID) {
    mac_address = realMac;
    chip_id = String(chipBuf);
  }
}

// ==============================================================================
// STEP 1: CONNECT TO WI-FI
// ==============================================================================
void connectToWiFi() {
  Serial.print("Connecting to Wi-Fi SSID: ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[✓] Wi-Fi Connected!");
    Serial.print("    Local IP Address: ");
    Serial.println(WiFi.localIP());
    Serial.print("    Signal RSSI     : ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");
  } else {
    Serial.println(
        "\n[✗] Wi-Fi Connection Failed. Please check SSID & Password.");
  }
}

// ==============================================================================
// STEP 2: AUTHENTICATE WITH CLOUD GATEWAY
// ==============================================================================
bool authenticateWithCloudGateway() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[!] Cannot authenticate: Wi-Fi offline");
    return false;
  }

  WiFiClient client;
  HTTPClient http;
  String endpoint =
      String(SERVER_BASE_URL) + "/api/v1/device-gateway/authenticate";

  Serial.print("\n[-->] Contacting Device Gateway: ");
  Serial.println(endpoint);

  http.setConnectTimeout(8000);
  http.setTimeout(8000);
  http.begin(client, endpoint);
  http.addHeader("Content-Type", "application/json");

  // Prepare JSON payload
  StaticJsonDocument<512> doc;
  doc["device_id"] = device_id;
  doc["chip_id"] = chip_id;
  doc["mac_address"] = mac_address;
  doc["device_token"] = device_token;
  doc["firmware_version"] = current_firmware_version;
  doc["boot_count"] = 1;

  String requestBody;
  serializeJson(doc, requestBody);

  Serial.println("[-->] Sending Handshake Payload:");
  serializeJsonPretty(doc, Serial);
  Serial.println();

  int httpCode = http.POST(requestBody);
  Serial.print("[<--] HTTP Response Code: ");
  Serial.println(httpCode);

  if (httpCode == 200) {
    String responseBody = http.getString();
    StaticJsonDocument<1024> respDoc;
    DeserializationError err = deserializeJson(respDoc, responseBody);

    if (!err) {
      session_jwt = respDoc["session_token"].as<String>();
      int configVer = respDoc["active_config_version"];
      is_authenticated = true;

      Serial.println("[✓] Authenticated Successfully!");
      Serial.print("    Assigned Client ID: ");
      Serial.println(respDoc["client_id"].as<String>());
      Serial.print("    Active Config Ver : ");
      Serial.println(configVer);
      Serial.print("    Session Token (JWT) Length: ");
      Serial.println(session_jwt.length());
      http.end();
      return true;
    } else {
      Serial.println("[✗] Error parsing JSON authentication response");
    }
  } else {
    String errorMsg = http.getString();
    Serial.print("[✗] Gateway Authentication Failed! Error code: ");
    Serial.print(httpCode);
    if (httpCode < 0) {
      Serial.print(" (");
      Serial.print(http.errorToString(httpCode));
      Serial.println(")");
    } else {
      Serial.println();
    }
    Serial.print("    Server response: ");
    Serial.println(errorMsg);
  }

  http.end();
  is_authenticated = false;
  return false;
}

// ==============================================================================
// STEP 3: SEND PERIODIC HEARTBEAT
// ==============================================================================
void sendHeartbeat() {
  if (!is_authenticated || WiFi.status() != WL_CONNECTED) {
    return;
  }

  WiFiClient client;
  HTTPClient http;
  String endpoint =
      String(SERVER_BASE_URL) + "/api/v1/device-gateway/heartbeat";

  http.setConnectTimeout(8000);
  http.setTimeout(8000);
  http.begin(client, endpoint);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", "Bearer " + session_jwt);

  StaticJsonDocument<512> doc;
  doc["current_firmware_version"] = current_firmware_version;
  doc["current_config_version"] = 1;
  doc["uptime_seconds"] = millis() / 1000;
  doc["free_heap_bytes"] = ESP.getFreeHeap();
  doc["wifi_rssi"] = WiFi.RSSI();
  doc["ip_address"] = WiFi.localIP().toString();

  String requestBody;
  serializeJson(doc, requestBody);

  int httpCode = http.POST(requestBody);
  if (httpCode == 200) {
    String resp = http.getString();
    StaticJsonDocument<512> respDoc;
    deserializeJson(respDoc, resp);

    bool inSync = respDoc["config_in_sync"];
    Serial.print("[♥] Heartbeat ACK | Uptime: ");
    Serial.print(millis() / 1000);
    Serial.print("s | Free Heap: ");
    Serial.print(ESP.getFreeHeap());
    Serial.print(" bytes | Config in Sync: ");
    Serial.println(inSync ? "YES (Up to date)" : "NO (Drift detected)");
  } else if (httpCode == 401) {
    Serial.println("[!] Session token expired. Re-authenticating...");
    authenticateWithCloudGateway();
  } else {
    Serial.print("[!] Heartbeat failed with code: ");
    Serial.println(httpCode);
  }

  http.end();
}

// ==============================================================================
// STEP 4: OVER-THE-AIR (OTA) FIRMWARE MANAGEMENT
// ==============================================================================
void reportOTAStatus(String deploymentId, String status, String errorMsg = "") {
  if (WiFi.status() != WL_CONNECTED) return;

  WiFiClient client;
  HTTPClient http;
  String endpoint = String(SERVER_BASE_URL) + "/api/v1/ota/status";

  http.setConnectTimeout(8000);
  http.setTimeout(8000);
  http.begin(client, endpoint);
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<512> doc;
  doc["deployment_id"] = deploymentId;
  doc["status"] = status;
  if (errorMsg.length() > 0) {
    doc["error_message"] = errorMsg;
  }

  String requestBody;
  serializeJson(doc, requestBody);
  http.POST(requestBody);
  http.end();
}

bool performOTAUpdate(String downloadUrl, String deploymentId, size_t binarySize, String version) {
  Serial.println("\n---------------------------------------------------------");
  Serial.println(">>> 🚀 OVER-THE-AIR (OTA) FLASH PROCEDURE INITIATED <<<");
  Serial.print("  Target Version : "); Serial.println(version);
  Serial.print("  Binary URL     : "); Serial.println(downloadUrl);
  Serial.print("  Binary Size    : "); Serial.print(binarySize); Serial.println(" bytes");
  Serial.println("---------------------------------------------------------");

  // 1. Report DOWNLOADING status to Cloud Gateway
  reportOTAStatus(deploymentId, "DOWNLOADING", "");

  WiFiClient client;
  HTTPClient http;

  http.setConnectTimeout(15000);
  http.setTimeout(45000);
  if (!http.begin(client, downloadUrl)) {
    Serial.println("[OTA ✗] Cannot connect to binary download endpoint!");
    reportOTAStatus(deploymentId, "FAILED", "Cannot reach download URL");
    return false;
  }

  int httpCode = http.GET();
  if (httpCode != HTTP_CODE_OK) {
    Serial.print("[OTA ✗] HTTP GET failed with code: ");
    Serial.println(httpCode);
    reportOTAStatus(deploymentId, "FAILED", "HTTP error " + String(httpCode));
    http.end();
    return false;
  }

  int contentLength = http.getSize();
  if (contentLength <= 0 && binarySize > 0) {
    contentLength = binarySize;
  }

  // 2. Initialize ESP32 Flash Partition Update
  bool canBegin = Update.begin(contentLength > 0 ? contentLength : UPDATE_SIZE_UNKNOWN, U_FLASH);
  if (!canBegin) {
    Serial.println("[OTA ✗] Not enough space in flash partition to begin OTA!");
    reportOTAStatus(deploymentId, "FAILED", "Not enough flash memory");
    http.end();
    return false;
  }

  Serial.println("[OTA] Partition ready. Streaming binary chunks to flash...");
  WiFiClient *stream = http.getStreamPtr();
  size_t written = 0;
  uint8_t buff[1024];
  unsigned long lastActivity = millis();

  while (http.connected() && (written < (size_t)contentLength || contentLength <= 0)) {
    size_t availableBytes = stream->available();
    if (availableBytes) {
      int readBytes = stream->readBytes(buff, min(availableBytes, sizeof(buff)));
      written += Update.write(buff, readBytes);
      lastActivity = millis();

      if (contentLength > 0 && (written % (32 * 1024) == 0 || (int)written == contentLength)) {
        int progress = (written * 100) / contentLength;
        Serial.printf("  [OTA Progress] %d%% (%u / %d bytes)\n", progress, written, contentLength);
      }
    } else {
      delay(5);
      if (millis() - lastActivity > 20000) {
        Serial.println("[OTA ✗] Timeout while reading binary stream!");
        Update.abort();
        reportOTAStatus(deploymentId, "FAILED", "Stream read timeout");
        http.end();
        return false;
      }
    }

    if (contentLength > 0 && (int)written >= contentLength) {
      break;
    }
  }

  // 3. Finalize and verify partition
  if (Update.end()) {
    if (Update.isFinished()) {
      Serial.println("\n[OTA ✓] FIRMWARE FLASH SUCCESSFUL!");
      Serial.print("  New Firmware Version : "); Serial.println(version);
      Serial.println("  Reporting status to cloud gateway...");

      reportOTAStatus(deploymentId, "SUCCESS", "");
      http.end();

      current_firmware_version = version;

      Serial.println("\n[✓] Rebooting into newly flashed firmware in 2 seconds...");
      Serial.flush();
      delay(2000);
      ESP.restart();
      return true;
    } else {
      Serial.println("[OTA ✗] Flashing ended but Update is not finished!");
      reportOTAStatus(deploymentId, "FAILED", "Flash verification incomplete");
    }
  } else {
    String err = "Update write error #" + String(Update.getError());
    Serial.print("[OTA ✗] "); Serial.println(err);
    reportOTAStatus(deploymentId, "FAILED", err);
  }

  http.end();
  return false;
}

void checkForPendingOTA() {
  if (!is_authenticated || WiFi.status() != WL_CONNECTED) {
    return;
  }

  WiFiClient client;
  HTTPClient http;
  String endpoint = String(SERVER_BASE_URL) + "/api/v1/ota/check/" + device_id;

  http.setConnectTimeout(8000);
  http.setTimeout(8000);
  http.begin(client, endpoint);

  int httpCode = http.GET();
  if (httpCode == 200) {
    String payload = http.getString();
    StaticJsonDocument<1024> doc;
    DeserializationError err = deserializeJson(doc, payload);

    if (!err && doc["has_update"] == true) {
      String deploymentId = doc["deployment_id"].as<String>();
      String targetVersion = doc["version"].as<String>();
      String binaryUrl = doc["binary_url"].as<String>();
      size_t fileSize = doc["file_size_bytes"].as<size_t>();

      Serial.println("\n=======================================================");
      Serial.println(">>> ⚡ CLOUD NOTIFICATION: FIRMWARE UPDATE READY! <<<");
      Serial.print("  Target Version  : "); Serial.println(targetVersion);
      Serial.print("  Deployment ID   : "); Serial.println(deploymentId);
      Serial.print("  Binary Size     : "); Serial.print(fileSize); Serial.println(" bytes");
      Serial.println("=======================================================");

      http.end();
      performOTAUpdate(binaryUrl, deploymentId, fileSize, targetVersion);
      return;
    }
  }

  http.end();
}

// ==============================================================================
// ARDUINO SETUP
// ==============================================================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("\n=============================================");
  Serial.println("  IoT Fleet Platform - ESP32 Hardware Node   ");
  Serial.println("=============================================");

  // Read and print hardware MAC and eFuse Chip ID
  readBoardHardwareIdentifiers();

  // Connect to local Wi-Fi
  connectToWiFi();

  // Authenticate with local/cloud backend
  if (WiFi.status() == WL_CONNECTED) {
    if (authenticateWithCloudGateway()) {
      // Check immediately for any pending OTA firmware
      checkForPendingOTA();
    }
  }
}

// ==============================================================================
// ARDUINO MAIN LOOP
// ==============================================================================
void loop() {
  // Reconnect Wi-Fi if lost
  if (WiFi.status() != WL_CONNECTED) {
    connectToWiFi();
  }

  // Send heartbeat every HEARTBEAT_INTERVAL_MS
  if (millis() - last_heartbeat_time >= HEARTBEAT_INTERVAL_MS) {
    last_heartbeat_time = millis();
    if (is_authenticated) {
      sendHeartbeat();
    } else {
      authenticateWithCloudGateway();
    }
  }

  // Check for OTA firmware updates periodically
  if (millis() - last_ota_check_time >= OTA_CHECK_INTERVAL_MS) {
    last_ota_check_time = millis();
    if (is_authenticated) {
      checkForPendingOTA();
    }
  }

  delay(100);
}
