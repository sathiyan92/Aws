/**
 * @file coin_offline_buffer.h
 * @brief LittleFS/Flash Circular Transaction Buffer for Offline Coin Vends
 *
 * Implements persistent ring buffer storage for offline coin transactions on ESP32,
 * allowing uninterrupted vending operations during network outages and reliable
 * reconciliation upon cloud reconnection.
 */

#ifndef COIN_OFFLINE_BUFFER_H
#define COIN_OFFLINE_BUFFER_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "coin_acceptor.h"

#ifdef __cplusplus
extern "C" {
#endif

#define COIN_OFFLINE_MAX_RECORDS        256     /* Max offline transactions retained */
#define COIN_OFFLINE_BUFFER_FILE        "/spiffs/coin_tx_buffer.bin"
#define COIN_OFFLINE_BATCH_SIZE         16      /* Max transactions uploaded per sync HTTP POST */

/**
 * @brief Initialize the offline transaction storage buffer.
 * Mounts LittleFS/SPIFFS filesystem and checks for existing pending transactions.
 * @return 0 on success, negative error code on failure.
 */
int coin_offline_buffer_init(void);

/**
 * @brief Append an offline coin vend transaction to the persistent ring buffer.
 * Automatically wraps around oldest synced records if capacity is reached.
 * @param record Pointer to the transaction record to persist.
 * @return 0 on success, negative error code on failure.
 */
int coin_offline_buffer_append(const coin_tx_record_t *record);

/**
 * @brief Retrieve a batch of unsynced transactions for cloud gateway reconciliation.
 * @param out_records Array to store retrieved unsynced records.
 * @param max_records Maximum number of records to retrieve in this batch.
 * @param out_count Pointer to variable receiving the count of returned records.
 * @return 0 on success, negative error code on failure.
 */
int coin_offline_buffer_get_unsynced(coin_tx_record_t *out_records, size_t max_records, size_t *out_count);

/**
 * @brief Mark a transaction as successfully synced to the cloud using its UUID.
 * @param tx_uuid Null-terminated UUIDv4 string of the synced transaction.
 * @return 0 on success, -1 if record not found.
 */
int coin_offline_buffer_mark_synced(const char *tx_uuid);

/**
 * @brief Mark multiple transactions as synced given an array of UUIDs.
 * @param uuids Array of UUID strings.
 * @param count Number of UUIDs in the array.
 * @return Number of records successfully marked as synced.
 */
size_t coin_offline_buffer_mark_batch_synced(const char * const *uuids, size_t count);

/**
 * @brief Get buffer statistics: total records stored and count of unsynced records.
 * @param out_total Pointer to receive total stored records count.
 * @param out_unsynced Pointer to receive unsynced records count.
 */
void coin_offline_buffer_get_stats(size_t *out_total, size_t *out_unsynced);

/**
 * @brief Purge all synced records to reclaim LittleFS flash memory.
 * @return Number of records purged.
 */
size_t coin_offline_buffer_purge_synced(void);

/**
 * @brief Clear the entire buffer (e.g. factory reset).
 */
void coin_offline_buffer_clear_all(void);

#ifdef __cplusplus
}
#endif

#endif /* COIN_OFFLINE_BUFFER_H */
