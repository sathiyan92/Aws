/**
 * @file system_tasks.c
 * @brief FreeRTOS Task Architecture & Thread-Safe IPC Implementation
 */

#include "system_tasks.h"
#include <string.h>
#include <stdio.h>

#ifdef ESP_PLATFORM
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/event_groups.h"
#include "esp_log.h"

static const char *TAG = "SYS_TASKS";
static QueueHandle_t s_telemetry_queue = NULL;
static QueueHandle_t s_command_queue = NULL;
static EventGroupHandle_t s_sys_events = NULL;

#else
/* Host Simulation Queues */
static telemetry_event_t s_sim_telemetry_buf[TELEMETRY_QUEUE_MAX_ITEMS];
static int s_sim_tel_head = 0, s_sim_tel_tail = 0, s_sim_tel_count = 0;

static command_event_t s_sim_command_buf[COMMAND_QUEUE_MAX_ITEMS];
static int s_sim_cmd_head = 0, s_sim_cmd_tail = 0, s_sim_cmd_count = 0;

static uint32_t s_sim_event_bits = 0;
#endif

int system_tasks_init(void)
{
#ifdef ESP_PLATFORM
    s_telemetry_queue = xQueueCreate(TELEMETRY_QUEUE_MAX_ITEMS, sizeof(telemetry_event_t));
    if (!s_telemetry_queue) {
        ESP_LOGE(TAG, "Failed to create telemetry queue");
        return -1;
    }

    s_command_queue = xQueueCreate(COMMAND_QUEUE_MAX_ITEMS, sizeof(command_event_t));
    if (!s_command_queue) {
        ESP_LOGE(TAG, "Failed to create command queue");
        return -1;
    }

    s_sys_events = xEventGroupCreate();
    if (!s_sys_events) {
        ESP_LOGE(TAG, "Failed to create system event group");
        return -1;
    }

    ESP_LOGI(TAG, "FreeRTOS queues and event groups initialized successfully.");
#else
    s_sim_tel_head = s_sim_tel_tail = s_sim_tel_count = 0;
    s_sim_cmd_head = s_sim_cmd_tail = s_sim_cmd_count = 0;
    s_sim_event_bits = 0;
#endif
    return 0;
}

int system_tasks_start_all(void)
{
#ifdef ESP_PLATFORM
    ESP_LOGI(TAG, "Starting system tasks with dual-core pinning...");
    /* In complete application, task loops are launched here:
     * Core 0: xTaskCreatePinnedToCore(net_task, ..., CORE_NETWORK_COMM);
     * Core 1: xTaskCreatePinnedToCore(io_task, ..., CORE_REALTIME_IO);
     */
#endif
    return 0;
}

int system_tasks_push_telemetry(const telemetry_event_t *event, uint32_t wait_ms)
{
    if (!event) return -1;

#ifdef ESP_PLATFORM
    if (!s_telemetry_queue) return -1;
    TickType_t ticks = (wait_ms == 0) ? 0 : pdMS_TO_TICKS(wait_ms);
    return (xQueueSend(s_telemetry_queue, event, ticks) == pdTRUE) ? 0 : -1;
#else
    if (s_sim_tel_count >= TELEMETRY_QUEUE_MAX_ITEMS) return -1;
    s_sim_telemetry_buf[s_sim_tel_tail] = *event;
    s_sim_tel_tail = (s_sim_tel_tail + 1) % TELEMETRY_QUEUE_MAX_ITEMS;
    s_sim_tel_count++;
    return 0;
#endif
}

int system_tasks_pop_telemetry(telemetry_event_t *out_event, uint32_t wait_ms)
{
    if (!out_event) return -1;

#ifdef ESP_PLATFORM
    if (!s_telemetry_queue) return -1;
    TickType_t ticks = (wait_ms == 0) ? 0 : pdMS_TO_TICKS(wait_ms);
    return (xQueueReceive(s_telemetry_queue, out_event, ticks) == pdTRUE) ? 0 : -1;
#else
    (void)wait_ms;
    if (s_sim_tel_count == 0) return -1;
    *out_event = s_sim_telemetry_buf[s_sim_tel_head];
    s_sim_tel_head = (s_sim_tel_head + 1) % TELEMETRY_QUEUE_MAX_ITEMS;
    s_sim_tel_count--;
    return 0;
#endif
}

int system_tasks_push_command(const command_event_t *cmd, uint32_t wait_ms)
{
    if (!cmd) return -1;

#ifdef ESP_PLATFORM
    if (!s_command_queue) return -1;
    TickType_t ticks = (wait_ms == 0) ? 0 : pdMS_TO_TICKS(wait_ms);
    return (xQueueSend(s_command_queue, cmd, ticks) == pdTRUE) ? 0 : -1;
#else
    if (s_sim_cmd_count >= COMMAND_QUEUE_MAX_ITEMS) return -1;
    s_sim_command_buf[s_sim_cmd_tail] = *cmd;
    s_sim_cmd_tail = (s_sim_cmd_tail + 1) % COMMAND_QUEUE_MAX_ITEMS;
    s_sim_cmd_count++;
    return 0;
#endif
}

int system_tasks_pop_command(command_event_t *out_cmd, uint32_t wait_ms)
{
    if (!out_cmd) return -1;

#ifdef ESP_PLATFORM
    if (!s_command_queue) return -1;
    TickType_t ticks = (wait_ms == 0) ? 0 : pdMS_TO_TICKS(wait_ms);
    return (xQueueReceive(s_command_queue, out_cmd, ticks) == pdTRUE) ? 0 : -1;
#else
    (void)wait_ms;
    if (s_sim_cmd_count == 0) return -1;
    *out_cmd = s_sim_command_buf[s_sim_cmd_head];
    s_sim_cmd_head = (s_sim_cmd_head + 1) % COMMAND_QUEUE_MAX_ITEMS;
    s_sim_cmd_count--;
    return 0;
#endif
}

void system_tasks_set_event(uint32_t event_bit)
{
#ifdef ESP_PLATFORM
    if (s_sys_events) {
        xEventGroupSetBits(s_sys_events, event_bit);
    }
#else
    s_sim_event_bits |= event_bit;
#endif
}

void system_tasks_clear_event(uint32_t event_bit)
{
#ifdef ESP_PLATFORM
    if (s_sys_events) {
        xEventGroupClearBits(s_sys_events, event_bit);
    }
#else
    s_sim_event_bits &= ~event_bit;
#endif
}

uint32_t system_tasks_wait_event(uint32_t event_bit, bool wait_all, uint32_t timeout_ms)
{
#ifdef ESP_PLATFORM
    if (!s_sys_events) return 0;
    TickType_t ticks = (timeout_ms == 0) ? 0 : pdMS_TO_TICKS(timeout_ms);
    return xEventGroupWaitBits(s_sys_events, event_bit, pdFALSE, wait_all ? pdTRUE : pdFALSE, ticks);
#else
    (void)wait_all;
    (void)timeout_ms;
    return s_sim_event_bits & event_bit;
#endif
}
