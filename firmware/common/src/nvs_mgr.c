/**
 * @file nvs_mgr.c
 * @brief Non-Volatile Storage (NVS) Manager Implementation
 *
 * Provides persistent storage for ESP32 hardware fleets with dual-target support:
 * - ESP_PLATFORM: Uses native ESP-IDF nvs_flash and nvs APIs.
 * - Host / Native Simulation: Uses persistent memory simulation for host testing.
 */

#include "nvs_mgr.h"
#include <string.h>
#include <stdio.h>

#ifdef ESP_PLATFORM
#include "esp_system.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "esp_log.h"
static const char *TAG = "NVS_MGR";
#else
/* Host Simulation Static Cache */
static device_identity_t s_sim_identity = {0};
static device_config_cache_t s_sim_config = {0};
static char s_sim_ssid[64] = "Apex-IoT-Warehouse";
static char s_sim_pass[64] = "Commercial@Wpa2Enterprise2026!";
static uint32_t s_sim_boot_count = 1;
static bool s_sim_initialized = false;
#endif

nvs_status_t nvs_mgr_init(void)
{
#ifdef ESP_PLATFORM
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to initialize NVS flash: %s", esp_err_to_name(ret));
        return NVS_STATUS_ERR_INIT_FAILED;
    }
    ESP_LOGI(TAG, "NVS flash partition initialized successfully.");
    return NVS_STATUS_OK;
#else
    s_sim_initialized = true;
    return NVS_STATUS_OK;
#endif
}

bool nvs_mgr_is_provisioned(void)
{
    device_identity_t id;
    if (nvs_mgr_read_identity(&id) == NVS_STATUS_OK) {
        return id.is_provisioned && (strlen(id.device_id) > 0);
    }
    return false;
}

nvs_status_t nvs_mgr_read_identity(device_identity_t *out_identity)
{
    if (!out_identity) return NVS_STATUS_ERR_READ_FAILED;

#ifdef ESP_PLATFORM
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NS_IDENTITY, NVS_READONLY, &handle);
    if (err != ESP_OK) return NVS_STATUS_ERR_NOT_FOUND;

    size_t required_size = sizeof(device_identity_t);
    err = nvs_get_blob(handle, "identity_blob", out_identity, &required_size);
    nvs_close(handle);

    return (err == ESP_OK) ? NVS_STATUS_OK : NVS_STATUS_ERR_READ_FAILED;
#else
    if (!s_sim_initialized) nvs_mgr_init();
    if (!s_sim_identity.is_provisioned) return NVS_STATUS_ERR_NOT_FOUND;
    memcpy(out_identity, &s_sim_identity, sizeof(device_identity_t));
    return NVS_STATUS_OK;
#endif
}

nvs_status_t nvs_mgr_write_identity(const device_identity_t *in_identity)
{
    if (!in_identity) return NVS_STATUS_ERR_WRITE_FAILED;

#ifdef ESP_PLATFORM
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NS_IDENTITY, NVS_READWRITE, &handle);
    if (err != ESP_OK) return NVS_STATUS_ERR_WRITE_FAILED;

    err = nvs_set_blob(handle, "identity_blob", in_identity, sizeof(device_identity_t));
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    }
    nvs_close(handle);

    return (err == ESP_OK) ? NVS_STATUS_OK : NVS_STATUS_ERR_WRITE_FAILED;
#else
    if (!s_sim_initialized) nvs_mgr_init();
    memcpy(&s_sim_identity, in_identity, sizeof(device_identity_t));
    s_sim_identity.is_provisioned = true;
    return NVS_STATUS_OK;
#endif
}

nvs_status_t nvs_mgr_read_config(device_config_cache_t *out_config)
{
    if (!out_config) return NVS_STATUS_ERR_READ_FAILED;

#ifdef ESP_PLATFORM
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NS_CONFIG, NVS_READONLY, &handle);
    if (err != ESP_OK) return NVS_STATUS_ERR_NOT_FOUND;

    size_t size = sizeof(device_config_cache_t);
    err = nvs_get_blob(handle, "cfg_cache", out_config, &size);
    nvs_close(handle);

    return (err == ESP_OK) ? NVS_STATUS_OK : NVS_STATUS_ERR_READ_FAILED;
#else
    if (!s_sim_initialized) nvs_mgr_init();
    memcpy(out_config, &s_sim_config, sizeof(device_config_cache_t));
    return NVS_STATUS_OK;
#endif
}

nvs_status_t nvs_mgr_write_config(const device_config_cache_t *in_config)
{
    if (!in_config) return NVS_STATUS_ERR_WRITE_FAILED;

#ifdef ESP_PLATFORM
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NS_CONFIG, NVS_READWRITE, &handle);
    if (err != ESP_OK) return NVS_STATUS_ERR_WRITE_FAILED;

    err = nvs_set_blob(handle, "cfg_cache", in_config, sizeof(device_config_cache_t));
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    }
    nvs_close(handle);

    return (err == ESP_OK) ? NVS_STATUS_OK : NVS_STATUS_ERR_WRITE_FAILED;
#else
    if (!s_sim_initialized) nvs_mgr_init();
    memcpy(&s_sim_config, in_config, sizeof(device_config_cache_t));
    return NVS_STATUS_OK;
#endif
}

nvs_status_t nvs_mgr_read_wifi_credentials(char *ssid, size_t max_ssid, char *password, size_t max_pass)
{
    if (!ssid || !password) return NVS_STATUS_ERR_READ_FAILED;

#ifdef ESP_PLATFORM
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NS_NET, NVS_READONLY, &handle);
    if (err != ESP_OK) return NVS_STATUS_ERR_NOT_FOUND;

    size_t s_len = max_ssid;
    size_t p_len = max_pass;
    err = nvs_get_str(handle, "wifi_ssid", ssid, &s_len);
    if (err == ESP_OK) {
        err = nvs_get_str(handle, "wifi_pass", password, &p_len);
    }
    nvs_close(handle);

    return (err == ESP_OK) ? NVS_STATUS_OK : NVS_STATUS_ERR_READ_FAILED;
#else
    if (!s_sim_initialized) nvs_mgr_init();
    strncpy(ssid, s_sim_ssid, max_ssid - 1);
    ssid[max_ssid - 1] = '\0';
    strncpy(password, s_sim_pass, max_pass - 1);
    password[max_pass - 1] = '\0';
    return NVS_STATUS_OK;
#endif
}

nvs_status_t nvs_mgr_write_wifi_credentials(const char *ssid, const char *password)
{
    if (!ssid || !password) return NVS_STATUS_ERR_WRITE_FAILED;

#ifdef ESP_PLATFORM
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NS_NET, NVS_READWRITE, &handle);
    if (err != ESP_OK) return NVS_STATUS_ERR_WRITE_FAILED;

    err = nvs_set_str(handle, "wifi_ssid", ssid);
    if (err == ESP_OK) {
        err = nvs_set_str(handle, "wifi_pass", password);
    }
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    }
    nvs_close(handle);

    return (err == ESP_OK) ? NVS_STATUS_OK : NVS_STATUS_ERR_WRITE_FAILED;
#else
    if (!s_sim_initialized) nvs_mgr_init();
    strncpy(s_sim_ssid, ssid, sizeof(s_sim_ssid) - 1);
    strncpy(s_sim_pass, password, sizeof(s_sim_pass) - 1);
    return NVS_STATUS_OK;
#endif
}

nvs_status_t nvs_mgr_increment_boot_count(uint32_t *out_boot_count)
{
#ifdef ESP_PLATFORM
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NS_IDENTITY, NVS_READWRITE, &handle);
    if (err != ESP_OK) return NVS_STATUS_ERR_WRITE_FAILED;

    uint32_t count = 0;
    nvs_get_u32(handle, "boot_cnt", &count);
    count++;
    nvs_set_u32(handle, "boot_cnt", count);
    nvs_commit(handle);
    nvs_close(handle);

    if (out_boot_count) *out_boot_count = count;
    return NVS_STATUS_OK;
#else
    if (!s_sim_initialized) nvs_mgr_init();
    s_sim_boot_count++;
    if (out_boot_count) *out_boot_count = s_sim_boot_count;
    return NVS_STATUS_OK;
#endif
}
