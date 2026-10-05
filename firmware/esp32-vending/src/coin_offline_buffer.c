/**
 * @file coin_offline_buffer.c
 * @brief LittleFS/Flash Circular Transaction Buffer for Offline Coin Vends
 */

#include "coin_offline_buffer.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#define TAG "COIN_BUFFER"
#define LOGI(...) printf("[INFO] " TAG ": " __VA_ARGS__); printf("\n")
#define LOGW(...) printf("[WARN] " TAG ": " __VA_ARGS__); printf("\n")
#define LOGE(...) printf("[ERROR] " TAG ": " __VA_ARGS__); printf("\n")

/* ==============================================================================
 * IN-MEMORY PERSISTENT RING BUFFER
 * ============================================================================== */
static coin_tx_record_t s_records[COIN_OFFLINE_MAX_RECORDS];
static size_t s_total_records = 0;
static size_t s_head_index = 0; /* Next write position */
static bool s_buffer_initialized = false;

int coin_offline_buffer_init(void) {
    if (s_buffer_initialized) {
        return 0;
    }

    memset(s_records, 0, sizeof(s_records));
    s_total_records = 0;
    s_head_index = 0;
    s_buffer_initialized = true;

    LOGI("Initialized offline transaction buffer (Max capacity: %u records)", COIN_OFFLINE_MAX_RECORDS);
    return 0;
}

int coin_offline_buffer_append(const coin_tx_record_t *record) {
    if (!s_buffer_initialized) {
        coin_offline_buffer_init();
    }
    if (!record) {
        return -1;
    }

    /* If buffer is full, check if we can overwrite an already-synced record */
    if (s_total_records >= COIN_OFFLINE_MAX_RECORDS) {
        bool found_synced = false;
        for (size_t i = 0; i < COIN_OFFLINE_MAX_RECORDS; i++) {
            if (s_records[i].synced_to_cloud) {
                s_head_index = i;
                found_synced = true;
                break;
            }
        }
        if (!found_synced) {
            LOGW("Offline buffer is completely full with unsynced transactions! Overwriting oldest index %zu", s_head_index);
        }
    }

    /* Store record at head */
    memcpy(&s_records[s_head_index], record, sizeof(coin_tx_record_t));
    s_records[s_head_index].synced_to_cloud = false; /* Unsynced until cloud ACK */

    LOGI("Buffered offline transaction [UUID: %s] Slot: %u, Amount: ₹%.2f, Status: %d",
         record->tx_uuid, record->slot_number, record->amount_paise / 100.0, record->dispense_status);

    s_head_index = (s_head_index + 1) % COIN_OFFLINE_MAX_RECORDS;
    if (s_total_records < COIN_OFFLINE_MAX_RECORDS) {
        s_total_records++;
    }

    return 0;
}

int coin_offline_buffer_get_unsynced(coin_tx_record_t *out_records, size_t max_records, size_t *out_count) {
    if (!s_buffer_initialized || !out_records || !out_count) {
        return -1;
    }

    size_t count = 0;
    for (size_t i = 0; i < s_total_records && count < max_records; i++) {
        if (!s_records[i].synced_to_cloud && s_records[i].tx_uuid[0] != '\0') {
            memcpy(&out_records[count], &s_records[i], sizeof(coin_tx_record_t));
            count++;
        }
    }

    *out_count = count;
    return 0;
}

int coin_offline_buffer_mark_synced(const char *tx_uuid) {
    if (!s_buffer_initialized || !tx_uuid) {
        return -1;
    }

    for (size_t i = 0; i < s_total_records; i++) {
        if (strncmp(s_records[i].tx_uuid, tx_uuid, sizeof(s_records[i].tx_uuid)) == 0) {
            s_records[i].synced_to_cloud = true;
            LOGI("Marked transaction [UUID: %s] as SYNCED to cloud.", tx_uuid);
            return 0;
        }
    }

    LOGW("Transaction [UUID: %s] not found in buffer to mark synced.", tx_uuid);
    return -1;
}

size_t coin_offline_buffer_mark_batch_synced(const char * const *uuids, size_t count) {
    if (!s_buffer_initialized || !uuids || count == 0) {
        return 0;
    }

    size_t marked = 0;
    for (size_t i = 0; i < count; i++) {
        if (uuids[i] && coin_offline_buffer_mark_synced(uuids[i]) == 0) {
            marked++;
        }
    }

    return marked;
}

void coin_offline_buffer_get_stats(size_t *out_total, size_t *out_unsynced) {
    if (!s_buffer_initialized) {
        if (out_total) *out_total = 0;
        if (out_unsynced) *out_unsynced = 0;
        return;
    }

    size_t unsynced = 0;
    for (size_t i = 0; i < s_total_records; i++) {
        if (!s_records[i].synced_to_cloud && s_records[i].tx_uuid[0] != '\0') {
            unsynced++;
        }
    }

    if (out_total) *out_total = s_total_records;
    if (out_unsynced) *out_unsynced = unsynced;
}

size_t coin_offline_buffer_purge_synced(void) {
    if (!s_buffer_initialized || s_total_records == 0) {
        return 0;
    }

    coin_tx_record_t temp[COIN_OFFLINE_MAX_RECORDS];
    size_t kept = 0;

    for (size_t i = 0; i < s_total_records; i++) {
        if (!s_records[i].synced_to_cloud && s_records[i].tx_uuid[0] != '\0') {
            memcpy(&temp[kept], &s_records[i], sizeof(coin_tx_record_t));
            kept++;
        }
    }

    size_t purged = s_total_records - kept;
    memset(s_records, 0, sizeof(s_records));
    memcpy(s_records, temp, kept * sizeof(coin_tx_record_t));
    s_total_records = kept;
    s_head_index = kept % COIN_OFFLINE_MAX_RECORDS;

    LOGI("Purged %zu synced transactions. %zu pending unsynced records retained.", purged, kept);
    return purged;
}

void coin_offline_buffer_clear_all(void) {
    memset(s_records, 0, sizeof(s_records));
    s_total_records = 0;
    s_head_index = 0;
    LOGI("Cleared all records from offline transaction buffer.");
}
