/**
 * @file system_tasks.h
 * @brief FreeRTOS Task Architecture & Thread-Safe IPC Queues
 *
 * Implements clean task separation between real-time hardware I/O (Core 1)
 * and cloud network communication (Core 0) using FreeRTOS queues and event groups.
 */

#ifndef SYSTEM_TASKS_H
#define SYSTEM_TASKS_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "firmware_config.h"

#ifdef __cplusplus
extern "C" {
#endif

/* System-wide Event Group Bits */
#define SYS_BIT_NET_CONNECTED          (1 << 0)
#define SYS_BIT_MQTT_CONNECTED         (1 << 1)
#define SYS_BIT_CONFIG_SYNCED          (1 << 2)
#define SYS_BIT_OTA_IN_PROGRESS        (1 << 3)
#define SYS_BIT_HARDWARE_FAULT         (1 << 4)

/* Telemetry Event Types from Real-Time I/O */
typedef enum {
    EVENT_TYPE_HEARTBEAT = 0,
    EVENT_TYPE_COIN_DROP,
    EVENT_TYPE_RFID_SWIPE,
    EVENT_TYPE_VEND_DISPENSE,
    EVENT_TYPE_STOCK_LOW,
    EVENT_TYPE_DOOR_TAMPER,
} telemetry_event_type_t;

/* Outbound Telemetry Message Structure passed via xQueueTelemetry */
typedef struct {
    telemetry_event_type_t event_type;
    uint32_t timestamp;
    int32_t numeric_val;                       /* Coin value, slot number, or pulse count */
    char auxiliary_str[64];                    /* Card UID, error text, or item code */
} telemetry_event_t;

/* Inbound Command Types from Cloud */
typedef enum {
    CMD_TYPE_DISPENSE_SLOT = 0,
    CMD_TYPE_UPDATE_CONFIG,
    CMD_TYPE_REBOOT_DEVICE,
    CMD_TYPE_BUZZER_ALERT,
    CMD_TYPE_OTA_TRIGGER,
} command_type_t;

/* Inbound Command Message Structure passed via xQueueCommands */
typedef struct {
    command_type_t cmd_type;
    uint32_t request_id;
    int32_t target_slot;
    char payload[256];
} command_event_t;

/**
 * @brief Initialize all FreeRTOS queues, mutexes, and event groups.
 * @return 0 on success, negative error code on failure.
 */
int system_tasks_init(void);

/**
 * @brief Start FreeRTOS worker tasks with pinned CPU affinities.
 * - Core 0: Network & MQTT Communication Tasks
 * - Core 1: Real-Time Hardware I/O Tasks
 * @return 0 on success.
 */
int system_tasks_start_all(void);

/**
 * @brief Push telemetry event from ISR or real-time I/O task into queue.
 * @param event Pointer to telemetry event.
 * @param wait_ms Maximum block time in milliseconds (0 if called from ISR).
 * @return 0 on success, -1 if queue full or timeout.
 */
int system_tasks_push_telemetry(const telemetry_event_t *event, uint32_t wait_ms);

/**
 * @brief Pop telemetry event in MQTT task for cloud publishing.
 * @param out_event Destination pointer.
 * @param wait_ms Maximum block time in milliseconds.
 * @return 0 on success, -1 if timeout.
 */
int system_tasks_pop_telemetry(telemetry_event_t *out_event, uint32_t wait_ms);

/**
 * @brief Push inbound cloud command into command execution queue.
 * @param cmd Pointer to command event.
 * @param wait_ms Maximum block time.
 * @return 0 on success.
 */
int system_tasks_push_command(const command_event_t *cmd, uint32_t wait_ms);

/**
 * @brief Pop command event in hardware execution task.
 * @param out_cmd Destination pointer.
 * @param wait_ms Maximum block time.
 * @return 0 on success.
 */
int system_tasks_pop_command(command_event_t *out_cmd, uint32_t wait_ms);

/**
 * @brief Set system event bit in event group.
 * @param event_bit Bitmask (e.g. SYS_BIT_NET_CONNECTED).
 */
void system_tasks_set_event(uint32_t event_bit);

/**
 * @brief Clear system event bit.
 * @param event_bit Bitmask to clear.
 */
void system_tasks_clear_event(uint32_t event_bit);

/**
 * @brief Wait for specified event bit(s).
 * @param event_bit Bitmask to wait on.
 * @param wait_all If true, waits for all bits; if false, any bit.
 * @param timeout_ms Timeout in milliseconds.
 * @return uint32_t active bits.
 */
uint32_t system_tasks_wait_event(uint32_t event_bit, bool wait_all, uint32_t timeout_ms);

#ifdef __cplusplus
}
#endif

#endif /* SYSTEM_TASKS_H */
