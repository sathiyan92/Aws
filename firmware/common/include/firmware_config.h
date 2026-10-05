/**
 * @file firmware_config.h
 * @brief Common Firmware Configuration, Pin Definitions, and FreeRTOS Parameters
 *
 * Defines system-wide parameters for ESP32 commercial IoT products (Vending & RFID).
 */

#ifndef FIRMWARE_CONFIG_H
#define FIRMWARE_CONFIG_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ==============================================================================
 * FIRMWARE METADATA & RELEASES
 * ============================================================================== */
#define FIRMWARE_VERSION_MAJOR          1
#define FIRMWARE_VERSION_MINOR          0
#define FIRMWARE_VERSION_PATCH          0
#define FIRMWARE_VERSION_STR            "v1.0.0"
#define FIRMWARE_BUILD_TIMESTAMP        __DATE__ " " __TIME__

/* Maximum string lengths */
#define DEVICE_ID_MAX_LEN               32   /* e.g., "VM-000001", "RFID-000001" */
#define CLIENT_ID_MAX_LEN               48   /* UUID format */
#define HARDWARE_SERIAL_MAX_LEN         48   /* e.g., "SN-2026-VM-0001" */
#define DEVICE_TOKEN_MAX_LEN            96   /* Cryptographic bearer/secret token */
#define TOPIC_BUFFER_MAX_LEN            160  /* Scoped MQTT topic path */
#define PAYLOAD_BUFFER_MAX_LEN          2048 /* JSON payload buffer */

/* ==============================================================================
 * HARDWARE MODULE BITFLAGS (Decoupled Feature Visibility at Edge)
 * ============================================================================== */
#define MODULE_FLAG_NONE                0x0000
#define MODULE_FLAG_QR_PAYMENT          (1 << 0) /* Dynamic UPI/Gateway QR display */
#define MODULE_FLAG_COIN_PAYMENT        (1 << 1) /* Mechanical pulse coin acceptor */
#define MODULE_FLAG_RFID_ACCESS         (1 << 2) /* 13.56MHz/125kHz RFID reader */
#define MODULE_FLAG_OFFLINE_SYNC        (1 << 3) /* Local LittleFS transaction buffer */
#define MODULE_FLAG_MDB_INTERNAL        (1 << 4) /* Multi-Drop Bus cashless peripheral */

/* ==============================================================================
 * FREERTOS TASK ARCHITECTURE & CPU CORE AFFINITY
 * Dual-Core ESP32: Core 0 (Network & Cloud) | Core 1 (Real-Time Hardware I/O)
 * ============================================================================== */
#define CORE_NETWORK_COMM               0
#define CORE_REALTIME_IO                1

/* Task Priorities (Higher number = Higher priority) */
#define PRIORITY_REALTIME_IO            6  /* Coin pulse ISR worker, RFID reader */
#define PRIORITY_NET_MANAGER            5  /* Wi-Fi / LTE-M link manager */
#define PRIORITY_MQTT_CLIENT            4  /* MQTT telemetry loop & heartbeats */
#define PRIORITY_SYS_MONITOR            2  /* Watchdog, heap checker, telemetry */

/* Task Stack Allocations (in bytes) */
#define STACK_SIZE_REALTIME_IO          4096
#define STACK_SIZE_NET_MANAGER          4096
#define STACK_SIZE_MQTT_CLIENT          6144
#define STACK_SIZE_SYS_MONITOR          2048

/* Inter-Task Queue Sizes */
#define TELEMETRY_QUEUE_MAX_ITEMS       32
#define COMMAND_QUEUE_MAX_ITEMS         16

/* ==============================================================================
 * NETWORK & MQTT CONNECTION TIMERS (Exponential Backoff)
 * ============================================================================== */
#define NET_RECONNECT_MIN_INTERVAL_MS   1000   /* 1 second initial retry */
#define NET_RECONNECT_MAX_INTERVAL_MS   60000  /* 60 seconds maximum backoff */
#define MQTT_HEARTBEAT_INTERVAL_SEC     30     /* Periodic keepalive ping */
#define MQTT_KEEP_ALIVE_SEC             60     /* Broker timeout */
#define MQTT_DEFAULT_PORT               8883   /* MQTTS (TLS 1.3) */
#define MQTT_INSECURE_PORT              1883   /* Plaintext (dev/local only) */

/* ==============================================================================
 * NVS STORAGE NAMESPACES
 * ============================================================================== */
#define NVS_NS_IDENTITY                 "dev_identity"
#define NVS_NS_NET                      "dev_network"
#define NVS_NS_CONFIG                   "dev_config"

#ifdef __cplusplus
}
#endif

#endif /* FIRMWARE_CONFIG_H */
