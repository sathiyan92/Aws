/**
 * @file coin_acceptor.h
 * @brief ESP32 Multi-Coin Acceptor Hardware Interrupt Driver & Edge Credit Accumulator
 *
 * Provides pulse train detection, hardware debouncing, configurable
 * pulse-to-denomination mapping, autonomous offline credit accumulation,
 * edge vend authorization, and change calculation for commercial vending machines.
 */

#ifndef COIN_ACCEPTOR_H
#define COIN_ACCEPTOR_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ==============================================================================
 * HARDWARE TIMING & ELECTRICAL CONSTANTS
 * ============================================================================== */
#define COIN_DEFAULT_GPIO_PIN           25      /* Configurable Coin Signal GPIO */
#define COIN_DEFAULT_INHIBIT_PIN        26      /* Hardware Inhibit/Enable Line */
#define COIN_MIN_PULSE_WIDTH_MS         20      /* Min pulse high/low width (reject transients) */
#define COIN_MAX_PULSE_WIDTH_MS         80      /* Max pulse duration */
#define COIN_INTER_PULSE_TIMEOUT_MS     250     /* Silence timeout delineating end of coin train */
#define COIN_DEFAULT_DEBOUNCE_MS        50      /* Hardware debounce window */
#define COIN_MAX_DENOMINATIONS          8       /* Max mapped coin denominations */
#define COIN_MAX_INSERTED_HISTORY       32      /* Max coins in current session */

/* ==============================================================================
 * ENUMS & STRUCTURES
 * ============================================================================== */

/** Operational mode of the coin acceptor */
typedef enum {
    COIN_MODE_PULSE_TRAIN = 0,   /* Electronic pulse train (e.g. CH-926 / generic) */
    COIN_MODE_SERIAL_MDB = 1,    /* MDB / Multi-Drop Bus serial peripheral */
} coin_acceptor_mode_t;

/** Operational state machine of the edge credit accumulator */
typedef enum {
    COIN_STATE_DISABLED = 0,     /* Acceptor line inhibited */
    COIN_STATE_IDLE = 1,         /* Ready, waiting for coin insertion */
    COIN_STATE_PULSING = 2,      /* Actively receiving pulse train */
    COIN_STATE_CREDIT_READY = 3,  /* Pulse train finished, credit accumulated */
    COIN_STATE_VENDING = 4,      /* Motor relay triggered for vend */
    COIN_STATE_DISPENSED = 5,    /* Drop sensor confirmed delivery */
    COIN_STATE_JAMMED = 6,       /* Vend attempted but drop sensor timed out */
} coin_state_t;

/** Vend dispense status */
typedef enum {
    COIN_DISPENSE_SUCCESS = 0,
    COIN_DISPENSE_FAILURE = 1,
    COIN_DISPENSE_JAMMED = 2,
} coin_dispense_status_t;

/** Pulse-to-denomination map entry */
typedef struct {
    uint8_t pulse_count;         /* Number of pulses generated (e.g. 1, 2, 5, 10) */
    uint32_t value_paise;        /* Value in smallest currency units (e.g. 100, 200, 500, 1000) */
} coin_denomination_map_t;

/** Configuration parameters for the coin acceptor driver */
typedef struct {
    uint8_t gpio_coin_pin;
    uint8_t gpio_inhibit_pin;
    coin_acceptor_mode_t mode;
    uint32_t debounce_ms;
    uint32_t inter_pulse_timeout_ms;
    bool change_dispenser_fitted;
    bool escrow_enabled;
    size_t denomination_count;
    coin_denomination_map_t denominations[COIN_MAX_DENOMINATIONS];
} coin_acceptor_config_t;

/** Breakdown of coins inserted in active session */
typedef struct {
    uint32_t count_1rs;          /* ₹1 / 100 paise coins */
    uint32_t count_2rs;          /* ₹2 / 200 paise coins */
    uint32_t count_5rs;          /* ₹5 / 500 paise coins */
    uint32_t count_10rs;         /* ₹10 / 1000 paise coins */
    uint32_t count_other;        /* Other configured denominations */
    uint32_t total_coins;        /* Total coin count */
} coin_counts_t;

/** Transaction record for offline persistence and cloud synchronization */
typedef struct {
    char tx_uuid[37];            /* UUIDv4 string */
    char device_id[32];          /* e.g. "VM-000001" */
    uint8_t slot_number;         /* Vended slot number (1-indexed) */
    char product_code[32];       /* Product SKU code */
    uint32_t amount_paise;       /* Total product price in paise */
    coin_counts_t coins_inserted;/* Denomination breakdown of cash used */
    uint32_t change_dispensed_paise; /* Change returned */
    coin_dispense_status_t dispense_status;
    uint64_t transacted_at_epoch;/* Unix timestamp (seconds) */
    bool is_offline_sync;        /* True if executed offline */
    bool synced_to_cloud;        /* False until ACK received from cloud */
} coin_tx_record_t;

/* ==============================================================================
 * DRIVER API FUNCTIONS
 * ============================================================================== */

/**
 * @brief Initialize the coin acceptor GPIO interrupt driver and state machine.
 * @param cfg Pointer to driver configuration parameters.
 * @return 0 on success, negative error code on failure.
 */
int coin_acceptor_init(const coin_acceptor_config_t *cfg);

/**
 * @brief Enable or disable the coin acceptor via the hardware inhibit line.
 * @param enable True to enable acceptance; false to inhibit coin insertion.
 */
void coin_acceptor_set_enabled(bool enable);

/**
 * @brief Handle a falling/rising edge interrupt event from the coin acceptor GPIO.
 * Designed to be called from the FreeRTOS ISR or real-time worker task.
 * @param pulse_width_ms Duration of the detected pulse.
 */
void coin_acceptor_on_pulse_event(uint32_t pulse_width_ms);

/**
 * @brief Periodic driver tick handler (run every 10-20ms) to check for pulse train timeouts.
 * Finalizes pulse train and converts pulse count to accumulated credit.
 * @param current_time_ms Monotonic time in milliseconds.
 * @return True if a coin pulse train was just completed and credit added.
 */
bool coin_acceptor_process_tick(uint32_t current_time_ms);

/**
 * @brief Get the current accumulated credit balance in paise.
 * @return Accumulated credit balance in paise.
 */
uint32_t coin_acceptor_get_credit_paise(void);

/**
 * @brief Get breakdown of coins inserted in the current session.
 * @param out_counts Pointer to structure to populate.
 */
void coin_acceptor_get_inserted_counts(coin_counts_t *out_counts);

/**
 * @brief Reset accumulated credit balance to zero (e.g. after vend or return).
 */
void coin_acceptor_reset_credit(void);

/**
 * @brief Determine if accumulated credit is sufficient to vend the requested slot.
 * @param slot_price_paise Price of the selected slot in paise.
 * @return True if credit >= price, false otherwise.
 */
bool coin_acceptor_can_vend(uint32_t slot_price_paise);

/**
 * @brief Execute autonomous edge vend: activates motor, checks drop sensor,
 * calculates change, records transaction, and updates credit.
 * @param slot_number Machine slot to dispense.
 * @param product_code Product SKU string.
 * @param slot_price_paise Product price in paise.
 * @param motor_pin GPIO pin for slot relay motor.
 * @param drop_sensor_confirmed True if physical drop sensor detected product.
 * @param out_tx Pointer to receive the generated transaction record.
 * @return Status of the vend execution (SUCCESS, FAILURE, JAMMED).
 */
coin_dispense_status_t coin_acceptor_execute_vend(
    uint8_t slot_number,
    const char *product_code,
    uint32_t slot_price_paise,
    uint8_t motor_pin,
    bool drop_sensor_confirmed,
    coin_tx_record_t *out_tx
);

/**
 * @brief Update denomination pulse mapping dynamically from cloud configuration.
 * @param mappings Pointer to array of denomination mappings.
 * @param count Number of mappings.
 * @return 0 on success, negative error code on failure.
 */
int coin_acceptor_update_denominations(const coin_denomination_map_t *mappings, size_t count);

/**
 * @brief Get current state of the coin acceptor state machine.
 */
coin_state_t coin_acceptor_get_state(void);

#ifdef __cplusplus
}
#endif

#endif /* COIN_ACCEPTOR_H */
