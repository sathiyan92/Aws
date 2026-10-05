/**
 * @file mqtt_mgr.c
 * @brief Resilient TLS 1.3 / MQTT Client Manager Implementation
 */

#include "mqtt_mgr.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#ifdef ESP_PLATFORM
#include "mqtt_client.h"
#include "esp_log.h"
static const char *TAG = "MQTT_MGR";
static esp_mqtt_client_handle_t s_client = NULL;
#else
/* Host Simulation Message Log */
typedef struct {
    char topic[128];
    char payload[512];
    int qos;
    bool retain;
} sim_mqtt_msg_t;

static sim_mqtt_msg_t s_last_published_msg = {0};
static int s_sim_msg_counter = 100;
#endif

static mqtt_config_t s_config;
static mqtt_state_t s_state = MQTT_STATE_DISCONNECTED;
static uint32_t s_retry_count = 0;

int mqtt_mgr_init(const mqtt_config_t *config)
{
    if (!config || strlen(config->device_id) == 0) return -1;
    memcpy(&s_config, config, sizeof(mqtt_config_t));
    s_state = MQTT_STATE_DISCONNECTED;
    s_retry_count = 0;

#ifdef ESP_PLATFORM
    esp_mqtt_client_config_t mqtt_cfg = {
        .broker.address.uri = s_config.broker_uri,
        .broker.address.port = s_config.port,
        .credentials.client_id = s_config.device_id,
        .credentials.authentication.password = s_config.auth_token,
        .session.keepalive = s_config.keepalive_sec > 0 ? s_config.keepalive_sec : MQTT_KEEP_ALIVE_SEC,
    };

    if (s_config.ca_cert_pem) {
        mqtt_cfg.broker.verification.certificate = s_config.ca_cert_pem;
    }
    if (s_config.client_cert_pem && s_config.client_key_pem) {
        mqtt_cfg.credentials.authentication.certificate = s_config.client_cert_pem;
        mqtt_cfg.credentials.authentication.key = s_config.client_key_pem;
    }

    s_client = esp_mqtt_client_init(&mqtt_cfg);
    if (!s_client) {
        ESP_LOGE(TAG, "Failed to initialize ESP-MQTT client");
        return -1;
    }
    ESP_LOGI(TAG, "MQTT Client initialized for device: %s", s_config.device_id);
#endif

    return 0;
}

int mqtt_mgr_start(void)
{
    s_state = MQTT_STATE_CONNECTING;

#ifdef ESP_PLATFORM
    if (s_client) {
        esp_err_t err = esp_mqtt_client_start(s_client);
        return (err == ESP_OK) ? 0 : -1;
    }
    return -1;
#else
    s_state = MQTT_STATE_CONNECTED;
    s_retry_count = 0;
    return 0;
#endif
}

int mqtt_mgr_stop(void)
{
#ifdef ESP_PLATFORM
    if (s_client) {
        esp_mqtt_client_stop(s_client);
    }
#endif
    s_state = MQTT_STATE_DISCONNECTED;
    return 0;
}

mqtt_state_t mqtt_mgr_get_state(void)
{
    return s_state;
}

int mqtt_mgr_format_topic(const char *subtopic, char *out_topic, size_t max_len)
{
    if (!subtopic || !out_topic || max_len < 32) return -1;
    int written = snprintf(out_topic, max_len, "devices/%s/%s", s_config.device_id, subtopic);
    return (written > 0 && (size_t)written < max_len) ? 0 : -1;
}

int mqtt_mgr_publish(const char *topic, const char *payload, int qos, bool retain)
{
    if (!topic || !payload) return -1;

#ifdef ESP_PLATFORM
    if (!s_client || s_state != MQTT_STATE_CONNECTED) return -1;
    return esp_mqtt_client_publish(s_client, topic, payload, strlen(payload), qos, retain ? 1 : 0);
#else
    strncpy(s_last_published_msg.topic, topic, sizeof(s_last_published_msg.topic) - 1);
    strncpy(s_last_published_msg.payload, payload, sizeof(s_last_published_msg.payload) - 1);
    s_last_published_msg.qos = qos;
    s_last_published_msg.retain = retain;
    return ++s_sim_msg_counter;
#endif
}

int mqtt_mgr_publish_heartbeat(uint32_t free_heap, int8_t rssi, uint32_t config_version)
{
    char topic[TOPIC_BUFFER_MAX_LEN];
    if (mqtt_mgr_format_topic("heartbeat", topic, sizeof(topic)) != 0) {
        return -1;
    }

    char payload[384];
    snprintf(payload, sizeof(payload),
        "{"
        "\"device_id\":\"%s\","
        "\"status\":\"ONLINE\","
        "\"firmware_version\":\"%s\","
        "\"config_version\":%lu,"
        "\"free_heap\":%lu,"
        "\"rssi\":%d,"
        "\"uptime_sec\":%lu"
        "}",
        s_config.device_id,
        FIRMWARE_VERSION_STR,
        (unsigned long)config_version,
        (unsigned long)free_heap,
        (int)rssi,
        (unsigned long)(time(NULL))
    );

    return mqtt_mgr_publish(topic, payload, 1, false);
}

int mqtt_mgr_subscribe(const char *topic, int qos, mqtt_message_handler_t handler, void *user_ctx)
{
    (void)handler;
    (void)user_ctx;
    if (!topic) return -1;

#ifdef ESP_PLATFORM
    if (!s_client) return -1;
    return esp_mqtt_client_subscribe(s_client, topic, qos);
#else
    return 0;
#endif
}

uint32_t mqtt_mgr_calculate_backoff_ms(uint32_t retry_attempt, uint32_t base_ms, uint32_t max_ms, uint32_t jitter_seed)
{
    if (base_ms == 0) base_ms = 1000;
    if (max_ms == 0) max_ms = 60000;

    /* Cap shift to 6 to prevent integer overflow (1 << 6 = 64) */
    uint32_t shift = (retry_attempt > 6) ? 6 : retry_attempt;
    uint32_t delay = base_ms * (1 << shift);

    if (delay > max_ms) {
        delay = max_ms;
    }

    /* Add jitter: 0% to 25% of delay */
    uint32_t max_jitter = delay / 4;
    uint32_t jitter = (max_jitter > 0) ? (jitter_seed % max_jitter) : 0;

    return delay + jitter;
}

int mqtt_mgr_publish_config_ack(uint32_t applied_version, const char *checksum, bool success, const char *error_msg)
{
    if (strlen(s_config.device_id) == 0) {
        return -1;
    }

    char topic[128];
    if (mqtt_mgr_format_topic("config/ack", topic, sizeof(topic)) != 0) {
        return -1;
    }

    char payload[384];
    const char *status_str = success ? "SUCCESS" : "ERROR";
    if (error_msg && strlen(error_msg) > 0) {
        snprintf(payload, sizeof(payload),
            "{\"device_id\":\"%s\",\"applied_version\":%lu,\"checksum\":\"%s\",\"status\":\"%s\",\"error_message\":\"%s\"}",
            s_config.device_id, (unsigned long)applied_version, checksum ? checksum : "", status_str, error_msg);
    } else {
        snprintf(payload, sizeof(payload),
            "{\"device_id\":\"%s\",\"applied_version\":%lu,\"checksum\":\"%s\",\"status\":\"%s\",\"error_message\":null}",
            s_config.device_id, (unsigned long)applied_version, checksum ? checksum : "", status_str);
    }

    return mqtt_mgr_publish(topic, payload, 1, false);
}

int mqtt_mgr_subscribe_config(mqtt_message_handler_t handler, void *user_ctx)
{
    if (strlen(s_config.device_id) == 0) {
        return -1;
    }

    char topic[128];
    if (mqtt_mgr_format_topic("config", topic, sizeof(topic)) != 0) {
        return -1;
    }

    return mqtt_mgr_subscribe(topic, 1, handler, user_ctx);
}

