/**
 * @file net_mgr.c
 * @brief Network Connection Hardware Abstraction Layer Implementation
 */

#include "net_mgr.h"
#include <string.h>
#include <stdio.h>

#ifdef ESP_PLATFORM
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"

static const char *TAG = "NET_MGR";
static esp_netif_t *s_netif_wifi = NULL;
static esp_netif_t *s_netif_eth = NULL;
#endif

/* Module Internal State */
static net_config_t s_config;
static net_state_t s_current_state = NET_STATE_DISCONNECTED;
static net_interface_t s_active_interface = NET_IF_NONE;
static net_event_cb_t s_event_callback = NULL;
static void *s_user_ctx = NULL;
static char s_ip_address[32] = "0.0.0.0";
static int8_t s_rssi = -65;
static uint32_t s_retry_count = 0;

static void notify_state_change(net_state_t new_state, net_interface_t active_if)
{
    s_current_state = new_state;
    s_active_interface = active_if;
    if (s_event_callback) {
        s_event_callback(new_state, active_if, s_user_ctx);
    }
}

int net_mgr_init(const net_config_t *config, net_event_cb_t callback, void *user_ctx)
{
    if (!config) return -1;
    memcpy(&s_config, config, sizeof(net_config_t));
    s_event_callback = callback;
    s_user_ctx = user_ctx;
    s_current_state = NET_STATE_DISCONNECTED;
    s_active_interface = NET_IF_NONE;

#ifdef ESP_PLATFORM
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    if (config->primary_interface == NET_IF_WIFI) {
        s_netif_wifi = esp_netif_create_default_wifi_sta();
        wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
        ESP_ERROR_CHECK(esp_wifi_init(&cfg));
        ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));

        wifi_config_t wifi_cfg = {0};
        strncpy((char *)wifi_cfg.sta.ssid, config->wifi_ssid, sizeof(wifi_cfg.sta.ssid) - 1);
        strncpy((char *)wifi_cfg.sta.password, config->wifi_password, sizeof(wifi_cfg.sta.password) - 1);
        wifi_cfg.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;

        ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg));
        ESP_LOGI(TAG, "Wi-Fi STA initialized for SSID: %s", config->wifi_ssid);
    }
#else
    strncpy(s_ip_address, "192.168.1.105", sizeof(s_ip_address) - 1);
    s_rssi = -58;
#endif

    return 0;
}

int net_mgr_start(void)
{
    notify_state_change(NET_STATE_CONNECTING, s_config.primary_interface);

#ifdef ESP_PLATFORM
    if (s_config.primary_interface == NET_IF_WIFI) {
        esp_wifi_start();
        esp_wifi_connect();
    }
#else
    /* Simulation: immediately resolve connected */
    notify_state_change(NET_STATE_CONNECTED, s_config.primary_interface);
#endif
    return 0;
}

int net_mgr_stop(void)
{
#ifdef ESP_PLATFORM
    if (s_active_interface == NET_IF_WIFI) {
        esp_wifi_disconnect();
        esp_wifi_stop();
    }
#endif
    notify_state_change(NET_STATE_DISCONNECTED, NET_IF_NONE);
    return 0;
}

net_state_t net_mgr_get_state(void)
{
    return s_current_state;
}

net_interface_t net_mgr_get_active_interface(void)
{
    return s_active_interface;
}

int net_mgr_get_ip_str(char *out_ip, size_t max_len)
{
    if (!out_ip || max_len < 8) return -1;

#ifdef ESP_PLATFORM
    if (s_active_interface == NET_IF_WIFI && s_netif_wifi) {
        esp_netif_ip_info_t ip_info;
        if (esp_netif_get_ip_info(s_netif_wifi, &ip_info) == ESP_OK) {
            snprintf(out_ip, max_len, IPSTR, IP2STR(&ip_info.ip));
            return 0;
        }
    }
    strncpy(out_ip, "0.0.0.0", max_len - 1);
    return -1;
#else
    strncpy(out_ip, s_ip_address, max_len - 1);
    out_ip[max_len - 1] = '\0';
    return 0;
#endif
}

int net_mgr_get_rssi(int8_t *out_rssi)
{
    if (!out_rssi) return -1;

#ifdef ESP_PLATFORM
    if (s_active_interface == NET_IF_WIFI) {
        wifi_ap_record_t ap_info;
        if (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK) {
            *out_rssi = ap_info.rssi;
            return 0;
        }
    }
    *out_rssi = -127;
    return -1;
#else
    *out_rssi = s_rssi;
    return 0;
#endif
}

int net_mgr_trigger_failover(void)
{
    if (!s_config.enable_automatic_failover || s_config.fallback_interface == NET_IF_NONE) {
        notify_state_change(NET_STATE_FAILED, s_active_interface);
        return -1;
    }

    notify_state_change(NET_STATE_FAILOVER, s_config.fallback_interface);
    s_active_interface = s_config.fallback_interface;

#ifdef ESP_PLATFORM
    ESP_LOGW(TAG, "Triggered failover from primary to fallback interface: %d", s_active_interface);
#else
    strncpy(s_ip_address, "10.144.82.19", sizeof(s_ip_address) - 1); /* Simulated LTE IP */
    s_rssi = -72;
#endif

    notify_state_change(NET_STATE_CONNECTED, s_active_interface);
    return 0;
}

void net_mgr_task_loop(void *pvParameters)
{
    (void)pvParameters;
    /* Main loop managed by FreeRTOS task */
}
