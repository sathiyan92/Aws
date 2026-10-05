/**
 * @file net_mgr.h
 * @brief Network Connection Hardware Abstraction Layer (HAL)
 *
 * Provides unified interface for Wi-Fi station, Ethernet, and Cellular LTE-M
 * modem fallback with event loop and reconnection management.
 */

#ifndef NET_MGR_H
#define NET_MGR_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Supported physical network interfaces */
typedef enum {
    NET_IF_NONE = 0,
    NET_IF_WIFI,
    NET_IF_ETHERNET,
    NET_IF_CELLULAR_LTE,
} net_interface_t;

/* Unified network states */
typedef enum {
    NET_STATE_DISCONNECTED = 0,
    NET_STATE_CONNECTING,
    NET_STATE_CONNECTED,
    NET_STATE_FAILOVER,
    NET_STATE_FAILED,
} net_state_t;

/* Configuration for network manager */
typedef struct {
    net_interface_t primary_interface;
    net_interface_t fallback_interface;
    bool enable_automatic_failover;
    uint32_t reconnect_timeout_ms;

    /* Wi-Fi credentials */
    char wifi_ssid[64];
    char wifi_password[64];

    /* Cellular LTE-M parameters */
    char cellular_apn[32];
    char cellular_pin[8];
} net_config_t;

/* Callback signature for network state transitions */
typedef void (*net_event_cb_t)(net_state_t new_state, net_interface_t active_if, void *user_ctx);

/**
 * @brief Initialize Network Manager HAL.
 * @param config Network configuration.
 * @param callback State change callback.
 * @param user_ctx User context pointer passed to callback.
 * @return 0 on success, negative error code on failure.
 */
int net_mgr_init(const net_config_t *config, net_event_cb_t callback, void *user_ctx);

/**
 * @brief Start network connection loop.
 * @return 0 on success.
 */
int net_mgr_start(void);

/**
 * @brief Stop network interfaces.
 * @return 0 on success.
 */
int net_mgr_stop(void);

/**
 * @brief Get current network state.
 * @return net_state_t current state.
 */
net_state_t net_mgr_get_state(void);

/**
 * @brief Get currently active network interface.
 * @return net_interface_t active interface.
 */
net_interface_t net_mgr_get_active_interface(void);

/**
 * @brief Retrieve IP address string.
 * @param out_ip Output buffer for IPv4 string (min 16 bytes).
 * @param max_len Maximum length of buffer.
 * @return 0 on success, negative on error.
 */
int net_mgr_get_ip_str(char *out_ip, size_t max_len);

/**
 * @brief Retrieve current RSSI / signal strength.
 * @param out_rssi Output pointer for RSSI in dBm.
 * @return 0 on success.
 */
int net_mgr_get_rssi(int8_t *out_rssi);

/**
 * @brief Trigger failover to fallback network interface (e.g. Wi-Fi -> LTE).
 * @return 0 on success.
 */
int net_mgr_trigger_failover(void);

/**
 * @brief Process network events (called by FreeRTOS net_task).
 */
void net_mgr_task_loop(void *pvParameters);

#ifdef __cplusplus
}
#endif

#endif /* NET_MGR_H */
