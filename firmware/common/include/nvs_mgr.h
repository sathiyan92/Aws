/**
 * @file nvs_mgr.h
 * @brief Non-Volatile Storage (NVS) Manager for ESP32 Firmware
 *
 * Persists immutable device identity, cryptographic credentials, dynamic configuration
 * revisions, and offline recovery flags.
 */

#ifndef NVS_MGR_H
#define NVS_MGR_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "firmware_config.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Result status codes */
typedef enum {
    NVS_STATUS_OK = 0,
    NVS_STATUS_ERR_INIT_FAILED = -1,
    NVS_STATUS_ERR_NOT_FOUND = -2,
    NVS_STATUS_ERR_WRITE_FAILED = -3,
    NVS_STATUS_ERR_READ_FAILED = -4,
    NVS_STATUS_ERR_BUFFER_OVERFLOW = -5,
    NVS_STATUS_ERR_CORRUPT_PAYLOAD = -6,
} nvs_status_t;

/* Device Identity Record stored permanently in NVS */
typedef struct {
    char device_id[DEVICE_ID_MAX_LEN];         /* e.g., "VM-000001" */
    char client_id[CLIENT_ID_MAX_LEN];         /* Assigned tenant UUID */
    char hardware_serial[HARDWARE_SERIAL_MAX_LEN]; /* e.g., "SN-2026-VM-0001" */
    char auth_token[DEVICE_TOKEN_MAX_LEN];     /* Secret provisioning bearer token */
    char product_type[24];                     /* "VENDING_MACHINE" or "RFID_ATTENDANCE" */
    bool is_provisioned;                       /* True after factory onboarding */
} device_identity_t;

/* Dynamic Configuration Cache stored in NVS */
typedef struct {
    uint32_t active_config_version;            /* Monotonic revision number */
    uint16_t enabled_modules_mask;             /* MODULE_FLAG_* bitmask */
    char config_checksum[65];                  /* SHA-256 of cloud JSON payload */
    uint32_t last_synced_timestamp;            /* Epoch seconds of last sync */
    bool is_synced;                            /* True if edge matches cloud */
} device_config_cache_t;

/* Function Declarations */

/**
 * @brief Initialize Non-Volatile Storage flash partition.
 * @return NVS_STATUS_OK on success, error code otherwise.
 */
nvs_status_t nvs_mgr_init(void);

/**
 * @brief Check if device has been provisioned with a permanent Device ID.
 * @return true if provisioned, false otherwise.
 */
bool nvs_mgr_is_provisioned(void);

/**
 * @brief Read permanent device identity from NVS.
 * @param out_identity Pointer to receive device identity data.
 * @return NVS_STATUS_OK on success.
 */
nvs_status_t nvs_mgr_read_identity(device_identity_t *out_identity);

/**
 * @brief Write permanent device identity to NVS during factory provisioning.
 * @param in_identity Pointer to device identity data to persist.
 * @return NVS_STATUS_OK on success.
 */
nvs_status_t nvs_mgr_write_identity(const device_identity_t *in_identity);

/**
 * @brief Read cached device configuration state.
 * @param out_config Pointer to receive configuration cache.
 * @return NVS_STATUS_OK on success.
 */
nvs_status_t nvs_mgr_read_config(device_config_cache_t *out_config);

/**
 * @brief Persist updated device configuration state after cloud synchronization.
 * @param in_config Pointer to configuration cache to write.
 * @return NVS_STATUS_OK on success.
 */
nvs_status_t nvs_mgr_write_config(const device_config_cache_t *in_config);

/**
 * @brief Read Wi-Fi network credentials.
 * @param ssid Output buffer for SSID.
 * @param max_ssid Maximum size of SSID buffer.
 * @param password Output buffer for password.
 * @param max_pass Maximum size of password buffer.
 * @return NVS_STATUS_OK on success.
 */
nvs_status_t nvs_mgr_read_wifi_credentials(char *ssid, size_t max_ssid, char *password, size_t max_pass);

/**
 * @brief Write Wi-Fi network credentials.
 * @param ssid Wi-Fi SSID to persist.
 * @param password Wi-Fi password to persist.
 * @return NVS_STATUS_OK on success.
 */
nvs_status_t nvs_mgr_write_wifi_credentials(const char *ssid, const char *password);

/**
 * @brief Read and increment system boot cycle counter.
 * @param out_boot_count Output pointer for updated boot count.
 * @return NVS_STATUS_OK on success.
 */
nvs_status_t nvs_mgr_increment_boot_count(uint32_t *out_boot_count);

#ifdef __cplusplus
}
#endif

#endif /* NVS_MGR_H */
