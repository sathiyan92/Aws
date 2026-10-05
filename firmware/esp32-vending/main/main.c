/**
 * @file main.c
 * @brief ESP32 Commercial Vending Machine Controller Firmware
 *
 * Bootstraps the embedded platform: NVS identity, FreeRTOS tasks, Network HAL,
 * MQTT connection, and real-time hardware I/O task pinning.
 */

#include <stdio.h>
#include <string.h>
#include "firmware_config.h"
#include "nvs_mgr.h"
#include "net_mgr.h"
#include "mqtt_mgr.h"
#include "system_tasks.h"

#ifdef ESP_PLATFORM
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
static const char *TAG = "VEND_MAIN";
#define LOGI(fmt, ...) ESP_LOGI(TAG, fmt, ##__VA_ARGS__)
#define LOGW(fmt, ...) ESP_LOGW(TAG, fmt, ##__VA_ARGS__)
#define LOGE(fmt, ...) ESP_LOGE(TAG, fmt, ##__VA_ARGS__)
#else
#define LOGI(fmt, ...) printf("[INFO][VEND_MAIN] " fmt "\n", ##__VA_ARGS__)
#define LOGW(fmt, ...) printf("[WARN][VEND_MAIN] " fmt "\n", ##__VA_ARGS__)
#define LOGE(fmt, ...) printf("[ERR ][VEND_MAIN] " fmt "\n", ##__VA_ARGS__)
#endif

/* Network State Callback */
static void on_network_event(net_state_t new_state, net_interface_t active_if, void *ctx)
{
    (void)ctx;
    if (new_state == NET_STATE_CONNECTED) {
        char ip[32];
        net_mgr_get_ip_str(ip, sizeof(ip));
        LOGI("Network Connected! Interface: %d, IP: %s", active_if, ip);
        system_tasks_set_event(SYS_BIT_NET_CONNECTED);

        /* Connect to cloud MQTT broker upon network ready */
        mqtt_mgr_start();
    } else if (new_state == NET_STATE_DISCONNECTED) {
        LOGW("Network Disconnected!");
        system_tasks_clear_event(SYS_BIT_NET_CONNECTED);
        mqtt_mgr_stop();
    }
}

void app_main(void)
{
    LOGI("==================================================");
    LOGI("ESP32 VENDING MACHINE CONTROLLER CORE FIRMWARE");
    LOGI("Firmware Version : %s", FIRMWARE_VERSION_STR);
    LOGI("Build Timestamp  : %s", FIRMWARE_BUILD_TIMESTAMP);
    LOGI("Architecture     : Dual-Core FreeRTOS with HAL");
    LOGI("==================================================");

    /* 1. Initialize Non-Volatile Storage */
    if (nvs_mgr_init() != NVS_STATUS_OK) {
        LOGE("FATAL: NVS Storage initialization failed!");
        return;
    }

    uint32_t boot_count = 0;
    nvs_mgr_increment_boot_count(&boot_count);
    LOGI("System Boot Cycle Count: %lu", (unsigned long)boot_count);

    /* 2. Load Device Identity */
    device_identity_t identity;
    if (nvs_mgr_read_identity(&identity) != NVS_STATUS_OK) {
        LOGW("Device unprovisioned in NVS. Using fallback factory credentials for VM-000001.");
        strncpy(identity.device_id, "VM-000001", sizeof(identity.device_id) - 1);
        strncpy(identity.hardware_serial, "SN-2026-VM-0001", sizeof(identity.hardware_serial) - 1);
        strncpy(identity.auth_token, "dev_token_VM-000001", sizeof(identity.auth_token) - 1);
        identity.is_provisioned = true;
        nvs_mgr_write_identity(&identity);
    }
    LOGI("Active Device ID: %s, Hardware Serial: %s", identity.device_id, identity.hardware_serial);

    /* 3. Load Dynamic Configuration Cache */
    device_config_cache_t config_cache;
    if (nvs_mgr_read_config(&config_cache) != NVS_STATUS_OK) {
        config_cache.active_config_version = 1;
        config_cache.enabled_modules_mask = MODULE_FLAG_QR_PAYMENT | MODULE_FLAG_COIN_PAYMENT;
        config_cache.is_synced = true;
        nvs_mgr_write_config(&config_cache);
    }
    LOGI("Active Config Version: v%lu | Enabled Modules Mask: 0x%04X",
         (unsigned long)config_cache.active_config_version,
         config_cache.enabled_modules_mask);

    if (config_cache.enabled_modules_mask & MODULE_FLAG_QR_PAYMENT) {
        LOGI("  [+] Dynamic QR Payment Module: ACTIVE");
    }
    if (config_cache.enabled_modules_mask & MODULE_FLAG_COIN_PAYMENT) {
        LOGI("  [+] Mechanical Coin Acceptor Module: ACTIVE");
    }

    /* 4. Initialize FreeRTOS Queues and Event Groups */
    if (system_tasks_init() != 0) {
        LOGE("FATAL: System tasks initialization failed!");
        return;
    }

    /* 5. Initialize Network Manager HAL */
    net_config_t net_cfg = {
        .primary_interface = NET_IF_WIFI,
        .fallback_interface = NET_IF_CELLULAR_LTE,
        .enable_automatic_failover = true,
        .reconnect_timeout_ms = 10000,
    };
    nvs_mgr_read_wifi_credentials(net_cfg.wifi_ssid, sizeof(net_cfg.wifi_ssid),
                                  net_cfg.wifi_password, sizeof(net_cfg.wifi_password));

    net_mgr_init(&net_cfg, on_network_event, NULL);

    /* 6. Configure Resilient MQTT Client */
    mqtt_config_t mqtt_cfg = {
        .port = MQTT_DEFAULT_PORT,
        .keepalive_sec = 60,
    };
    strncpy(mqtt_cfg.broker_uri, "mqtts://cloud.iotfleet.com:8883", sizeof(mqtt_cfg.broker_uri) - 1);
    strncpy(mqtt_cfg.device_id, identity.device_id, sizeof(mqtt_cfg.device_id) - 1);
    strncpy(mqtt_cfg.auth_token, identity.auth_token, sizeof(mqtt_cfg.auth_token) - 1);

    mqtt_mgr_init(&mqtt_cfg);

    /* 7. Start Network Connection */
    net_mgr_start();

    /* 8. Start Multi-Task Worker Loop */
    system_tasks_start_all();

    LOGI("ESP32 Vending Controller base core running normally.");
}
