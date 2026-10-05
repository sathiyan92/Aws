/**
 * @file mqtt_mgr.h
 * @brief Resilient TLS 1.3 / MQTT Client Manager
 *
 * Implements MQTT communication with the Cloud IoT broker with automatic exponential
 * backoff, topic isolation scoped by Device ID, and keepalive heartbeats.
 */

#ifndef MQTT_MGR_H
#define MQTT_MGR_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "firmware_config.h"

#ifdef __cplusplus
extern "C" {
#endif

/* MQTT connection states */
typedef enum {
    MQTT_STATE_DISCONNECTED = 0,
    MQTT_STATE_CONNECTING,
    MQTT_STATE_CONNECTED,
    MQTT_STATE_RECONNECTING,
    MQTT_STATE_ERROR,
} mqtt_state_t;

/* MQTT message callback signature */
typedef void (*mqtt_message_handler_t)(const char *topic, const char *payload, size_t len, void *ctx);

/* MQTT Client configuration */
typedef struct {
    char broker_uri[128];                      /* e.g., "mqtts://broker.iotfleet.com:8883" */
    uint16_t port;                             /* 8883 or 1883 */
    char device_id[DEVICE_ID_MAX_LEN];         /* MQTT Client ID */
    char auth_token[DEVICE_TOKEN_MAX_LEN];     /* Token authentication */
    const char *ca_cert_pem;                   /* Cloud TLS root CA certificate */
    const char *client_cert_pem;               /* Optional mTLS client certificate */
    const char *client_key_pem;                /* Optional mTLS client private key */
    uint32_t keepalive_sec;                    /* Keepalive ping interval */
} mqtt_config_t;

/**
 * @brief Initialize MQTT manager.
 * @param config Pointer to client configuration.
 * @return 0 on success, negative error code on failure.
 */
int mqtt_mgr_init(const mqtt_config_t *config);

/**
 * @brief Start MQTT connection loop.
 * @return 0 on success.
 */
int mqtt_mgr_start(void);

/**
 * @brief Disconnect and stop MQTT client.
 * @return 0 on success.
 */
int mqtt_mgr_stop(void);

/**
 * @brief Get current MQTT state.
 * @return mqtt_state_t current state.
 */
mqtt_state_t mqtt_mgr_get_state(void);

/**
 * @brief Publish payload to a topic.
 * @param topic Destination topic path.
 * @param payload Message payload string.
 * @param qos Quality of Service (0, 1, or 2).
 * @param retain Retain flag.
 * @return Message ID on success, negative on error.
 */
int mqtt_mgr_publish(const char *topic, const char *payload, int qos, bool retain);

/**
 * @brief Publish standard device heartbeat telemetry.
 * @param free_heap Current free heap in bytes.
 * @param rssi Current Wi-Fi/LTE RSSI in dBm.
 * @param config_version Active configuration version number.
 * @return Message ID on success, negative on error.
 */
int mqtt_mgr_publish_heartbeat(uint32_t free_heap, int8_t rssi, uint32_t config_version);

/**
 * @brief Register inbound message handler for a topic.
 * @param topic Topic to subscribe to.
 * @param qos QoS level.
 * @param handler Function callback.
 * @param user_ctx User context.
 * @return 0 on success.
 */
int mqtt_mgr_subscribe(const char *topic, int qos, mqtt_message_handler_t handler, void *user_ctx);

/**
 * @brief Calculate exponential backoff duration with random jitter.
 * @param retry_attempt Current consecutive retry attempt (0, 1, 2...).
 * @param base_ms Base reconnect delay in milliseconds (e.g., 1000).
 * @param max_ms Maximum backoff ceiling in milliseconds (e.g., 60000).
 * @param jitter_seed Random seed for jitter generation.
 * @return Calculated backoff delay in milliseconds.
 */
uint32_t mqtt_mgr_calculate_backoff_ms(uint32_t retry_attempt, uint32_t base_ms, uint32_t max_ms, uint32_t jitter_seed);

/**
 * @brief Generate topic string scoped by Device ID.
 * @param subtopic e.g. "heartbeat", "telemetry", "config", "commands", "ota"
 * @param out_topic Output buffer.
 * @param max_len Maximum output buffer size.
 * @return 0 on success.
 */
int mqtt_mgr_format_topic(const char *subtopic, char *out_topic, size_t max_len);

/**
 * @brief Publish configuration synchronization acknowledgment to cloud.
 * Topic: devices/{device_id}/config/ack
 * @param applied_version Revision number committed to NVS.
 * @param checksum SHA-256 checksum validated.
 * @param success True if successfully applied, false if error.
 * @param error_msg Optional error message if failed.
 * @return Message ID on success, negative on error.
 */
int mqtt_mgr_publish_config_ack(uint32_t applied_version, const char *checksum, bool success, const char *error_msg);

/**
 * @brief Subscribe to device configuration topic: devices/{device_id}/config.
 * @param handler Callback to receive configuration update JSON.
 * @param user_ctx User context.
 * @return 0 on success.
 */
int mqtt_mgr_subscribe_config(mqtt_message_handler_t handler, void *user_ctx);

#ifdef __cplusplus
}
#endif

#endif /* MQTT_MGR_H */
