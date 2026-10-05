/**
 * @file coin_acceptor.c
 * @brief ESP32 Multi-Coin Acceptor Hardware Interrupt Driver & Edge Credit Accumulator
 */

#include "coin_acceptor.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <time.h>

#define TAG "COIN_ACCEPTOR"
#define LOGI(...) printf("[INFO] " TAG ": " __VA_ARGS__); printf("\n")
#define LOGW(...) printf("[WARN] " TAG ": " __VA_ARGS__); printf("\n")
#define LOGE(...) printf("[ERROR] " TAG ": " __VA_ARGS__); printf("\n")

/* ==============================================================================
 * STATIC DRIVER STATE
 * ============================================================================== */
static coin_acceptor_config_t s_config;
static coin_state_t s_state = COIN_STATE_DISABLED;
static uint32_t s_accumulated_credit_paise = 0;
static coin_counts_t s_session_counts = {0};

/* Pulse train detector state */
static uint8_t s_current_pulse_count = 0;
static uint32_t s_last_pulse_timestamp_ms = 0;
static bool s_is_pulsing = false;
static bool s_driver_initialized = false;

/* ==============================================================================
 * UTILITY FUNCTIONS
 * ============================================================================== */

static void generate_simple_uuid(char *out_uuid, size_t max_len) {
    if (max_len < 37) return;
    /* Deterministic/pseudorandom UUIDv4 format */
    uint32_t r1 = (uint32_t)rand();
    uint32_t r2 = (uint32_t)rand();
    uint32_t r3 = (uint32_t)rand();
    uint32_t r4 = (uint32_t)rand();
    snprintf(out_uuid, max_len, "%08x-%04x-4%03x-%04x-%04x%08x",
             r1,
             (uint16_t)(r2 & 0xFFFF),
             (uint16_t)((r2 >> 16) & 0x0FFF),
             (uint16_t)((r3 & 0x3FFF) | 0x8000),
             (uint16_t)((r3 >> 16) & 0xFFFF),
             r4);
}

static uint32_t resolve_pulses_to_paise(uint8_t pulse_count) {
    for (size_t i = 0; i < s_config.denomination_count; i++) {
        if (s_config.denominations[i].pulse_count == pulse_count) {
            return s_config.denominations[i].value_paise;
        }
    }
    LOGW("Unmapped pulse count: %u pulses! Discarding as unrecognized denomination.", pulse_count);
    return 0;
}

static void record_coin_denomination(uint32_t value_paise) {
    s_session_counts.total_coins++;
    if (value_paise == 100) {
        s_session_counts.count_1rs++;
    } else if (value_paise == 200) {
        s_session_counts.count_2rs++;
    } else if (value_paise == 500) {
        s_session_counts.count_5rs++;
    } else if (value_paise == 1000) {
        s_session_counts.count_10rs++;
    } else {
        s_session_counts.count_other++;
    }
}

/* ==============================================================================
 * PUBLIC API IMPLEMENTATION
 * ============================================================================== */

int coin_acceptor_init(const coin_acceptor_config_t *cfg) {
    if (!cfg) {
        return -1;
    }

    memcpy(&s_config, cfg, sizeof(coin_acceptor_config_t));
    s_accumulated_credit_paise = 0;
    memset(&s_session_counts, 0, sizeof(coin_counts_t));
    s_current_pulse_count = 0;
    s_last_pulse_timestamp_ms = 0;
    s_is_pulsing = false;

    /* Populate default pulse denominations if not configured */
    if (s_config.denomination_count == 0) {
        s_config.denomination_count = 4;
        s_config.denominations[0] = (coin_denomination_map_t){ .pulse_count = 1,  .value_paise = 100 };  /* ₹1 */
        s_config.denominations[1] = (coin_denomination_map_t){ .pulse_count = 2,  .value_paise = 200 };  /* ₹2 */
        s_config.denominations[2] = (coin_denomination_map_t){ .pulse_count = 5,  .value_paise = 500 };  /* ₹5 */
        s_config.denominations[3] = (coin_denomination_map_t){ .pulse_count = 10, .value_paise = 1000 }; /* ₹10 */
    }

    if (s_config.inter_pulse_timeout_ms == 0) {
        s_config.inter_pulse_timeout_ms = COIN_INTER_PULSE_TIMEOUT_MS;
    }
    if (s_config.debounce_ms == 0) {
        s_config.debounce_ms = COIN_DEFAULT_DEBOUNCE_MS;
    }

    s_state = COIN_STATE_IDLE;
    s_driver_initialized = true;

    LOGI("Initialized coin acceptor on GPIO %u (Debounce: %ums, Timeout: %ums, Denominations: %zu)",
         s_config.gpio_coin_pin, (unsigned int)s_config.debounce_ms,
         (unsigned int)s_config.inter_pulse_timeout_ms, s_config.denomination_count);

    return 0;
}

void coin_acceptor_set_enabled(bool enable) {
    if (!s_driver_initialized) return;

    if (enable) {
        s_state = COIN_STATE_IDLE;
        LOGI("Hardware inhibit line RELEASED. Coin acceptor ENABLED.");
    } else {
        s_state = COIN_STATE_DISABLED;
        s_is_pulsing = false;
        s_current_pulse_count = 0;
        LOGI("Hardware inhibit line ASSERTED. Coin acceptor DISABLED.");
    }
}

void coin_acceptor_on_pulse_event(uint32_t pulse_width_ms) {
    if (!s_driver_initialized || s_state == COIN_STATE_DISABLED) {
        return;
    }

    /* Hardware pulse filtering: reject electrical transients shorter than min width */
    if (pulse_width_ms < COIN_MIN_PULSE_WIDTH_MS) {
        LOGW("Transient spike rejected: %ums < min %ums", (unsigned int)pulse_width_ms, COIN_MIN_PULSE_WIDTH_MS);
        return;
    }
    if (pulse_width_ms > COIN_MAX_PULSE_WIDTH_MS) {
        LOGW("Stuck pulse rejected: %ums > max %ums", (unsigned int)pulse_width_ms, COIN_MAX_PULSE_WIDTH_MS);
        return;
    }

    /* Valid pulse registered */
    s_current_pulse_count++;
    s_is_pulsing = true;
    s_state = COIN_STATE_PULSING;

    /* Update timestamp for timeout detection (approx current clock) */
    s_last_pulse_timestamp_ms = (uint32_t)(clock() * 1000 / CLOCKS_PER_SEC);

    LOGI("Pulse detected [#%u] (width: %ums)", s_current_pulse_count, (unsigned int)pulse_width_ms);
}

bool coin_acceptor_process_tick(uint32_t current_time_ms) {
    if (!s_driver_initialized || !s_is_pulsing) {
        return false;
    }

    /* Check if inter-pulse train silence duration has exceeded timeout */
    uint32_t elapsed_ms = current_time_ms - s_last_pulse_timestamp_ms;
    if (elapsed_ms >= s_config.inter_pulse_timeout_ms) {
        /* Pulse train finished: convert pulse count to coin value */
        uint8_t final_pulses = s_current_pulse_count;
        s_current_pulse_count = 0;
        s_is_pulsing = false;

        uint32_t coin_value = resolve_pulses_to_paise(final_pulses);
        if (coin_value > 0) {
            s_accumulated_credit_paise += coin_value;
            record_coin_denomination(coin_value);
            s_state = COIN_STATE_CREDIT_READY;

            LOGI("Coin Accepted! %u pulses -> ₹%.2f (Active Credit: ₹%.2f)",
                 final_pulses, coin_value / 100.0, s_accumulated_credit_paise / 100.0);
            return true;
        } else {
            s_state = (s_accumulated_credit_paise > 0) ? COIN_STATE_CREDIT_READY : COIN_STATE_IDLE;
        }
    }

    return false;
}

uint32_t coin_acceptor_get_credit_paise(void) {
    return s_accumulated_credit_paise;
}

void coin_acceptor_get_inserted_counts(coin_counts_t *out_counts) {
    if (out_counts) {
        memcpy(out_counts, &s_session_counts, sizeof(coin_counts_t));
    }
}

void coin_acceptor_reset_credit(void) {
    s_accumulated_credit_paise = 0;
    memset(&s_session_counts, 0, sizeof(coin_counts_t));
    s_state = COIN_STATE_IDLE;
    LOGI("Credit balance reset to ₹0.00");
}

bool coin_acceptor_can_vend(uint32_t slot_price_paise) {
    return (s_accumulated_credit_paise >= slot_price_paise && slot_price_paise > 0);
}

coin_dispense_status_t coin_acceptor_execute_vend(
    uint8_t slot_number,
    const char *product_code,
    uint32_t slot_price_paise,
    uint8_t motor_pin,
    bool drop_sensor_confirmed,
    coin_tx_record_t *out_tx
) {
    if (!coin_acceptor_can_vend(slot_price_paise)) {
        LOGE("Cannot vend slot %u: Insufficient credit (Has: ₹%.2f, Needs: ₹%.2f)",
             slot_number, s_accumulated_credit_paise / 100.0, slot_price_paise / 100.0);
        return COIN_DISPENSE_FAILURE;
    }

    s_state = COIN_STATE_VENDING;
    LOGI("Executing edge vend: Slot %u (Motor Pin GPIO %u, Price: ₹%.2f)",
         slot_number, motor_pin, slot_price_paise / 100.0);

    /* Deduct product price from credit balance */
    s_accumulated_credit_paise -= slot_price_paise;
    uint32_t change_due_paise = s_accumulated_credit_paise;

    /* Handle change dispenser / escrow */
    uint32_t change_dispensed = 0;
    if (change_due_paise > 0) {
        if (s_config.change_dispenser_fitted) {
            LOGI("Dispensing change: ₹%.2f via coin hopper", change_due_paise / 100.0);
            change_dispensed = change_due_paise;
            s_accumulated_credit_paise = 0;
        } else {
            LOGW("Change dispenser not fitted. Balance ₹%.2f remains in escrow.", change_due_paise / 100.0);
        }
    }

    /* Evaluate physical drop sensor */
    coin_dispense_status_t status;
    if (drop_sensor_confirmed) {
        s_state = COIN_STATE_DISPENSED;
        status = COIN_DISPENSE_SUCCESS;
        LOGI("Dispense SUCCESS: Drop sensor confirmed product falling from slot %u", slot_number);
    } else {
        s_state = COIN_STATE_JAMMED;
        status = COIN_DISPENSE_JAMMED;
        LOGE("Dispense JAMMED: Motor actuated on slot %u but drop sensor timed out!", slot_number);
    }

    /* Build transaction record */
    if (out_tx) {
        memset(out_tx, 0, sizeof(coin_tx_record_t));
        generate_simple_uuid(out_tx->tx_uuid, sizeof(out_tx->tx_uuid));
        strncpy(out_tx->device_id, "VM-000001", sizeof(out_tx->device_id) - 1);
        out_tx->slot_number = slot_number;
        if (product_code) {
            strncpy(out_tx->product_code, product_code, sizeof(out_tx->product_code) - 1);
        }
        out_tx->amount_paise = slot_price_paise;
        memcpy(&out_tx->coins_inserted, &s_session_counts, sizeof(coin_counts_t));
        out_tx->change_dispensed_paise = change_dispensed;
        out_tx->dispense_status = status;
        out_tx->transacted_at_epoch = (uint64_t)time(NULL);
        out_tx->is_offline_sync = true;
        out_tx->synced_to_cloud = false;
    }

    /* If dispense was successful, reset session coin counts for the next customer */
    if (status == COIN_DISPENSE_SUCCESS) {
        memset(&s_session_counts, 0, sizeof(coin_counts_t));
    }

    return status;
}

int coin_acceptor_update_denominations(const coin_denomination_map_t *mappings, size_t count) {
    if (!mappings || count == 0 || count > COIN_MAX_DENOMINATIONS) {
        return -1;
    }

    s_config.denomination_count = count;
    memcpy(s_config.denominations, mappings, count * sizeof(coin_denomination_map_t));

    LOGI("Updated pulse denomination mappings (%zu entries):", count);
    for (size_t i = 0; i < count; i++) {
        LOGI("  %u pulses -> ₹%.2f (%u paise)",
             s_config.denominations[i].pulse_count,
             s_config.denominations[i].value_paise / 100.0,
             s_config.denominations[i].value_paise);
    }

    return 0;
}

coin_state_t coin_acceptor_get_state(void) {
    return s_state;
}
