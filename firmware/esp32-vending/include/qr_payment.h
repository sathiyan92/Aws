/**
 * @file qr_payment.h
 * @brief Dynamic UPI QR Payment Display Engine & Countdown Timer for ESP32 Vending
 *
 * Implements transaction-based dynamic QR payment states, countdown timers,
 * display rendering handlers, and hybrid-mode cancellation upon cash insertion.
 */

#ifndef QR_PAYMENT_H
#define QR_PAYMENT_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define QR_DEFAULT_TIMEOUT_SEC          180
#define QR_PAYLOAD_MAX_LEN              512
#define QR_ORDER_ID_MAX_LEN             48
#define QR_ORDER_NUM_MAX_LEN            32
#define QR_TOKEN_MAX_LEN                128

typedef enum {
    QR_PAYMENT_STATE_IDLE = 0,
    QR_PAYMENT_STATE_REQUESTING = 1,
    QR_PAYMENT_STATE_DISPLAYING = 2,
    QR_PAYMENT_STATE_AUTHORIZED = 3,
    QR_PAYMENT_STATE_EXPIRED = 4,
    QR_PAYMENT_STATE_CANCELLED = 5,
} qr_payment_state_t;

typedef struct {
    char order_id[QR_ORDER_ID_MAX_LEN];
    char order_number[QR_ORDER_NUM_MAX_LEN];
    uint8_t slot_number;
    uint32_t amount_paise;
    char upi_payload[QR_PAYLOAD_MAX_LEN];
    uint16_t timeout_seconds;
    int32_t seconds_remaining;
    qr_payment_state_t state;
    char dispense_token[QR_TOKEN_MAX_LEN];
    uint64_t session_started_ms;
} qr_payment_session_t;

/**
 * @brief Initialize the dynamic QR payment subsystem.
 * @return 0 on success.
 */
int qr_payment_init(void);

/**
 * @brief Start a dynamic QR payment session on the edge device display.
 * @param slot_number Vending machine slot selected by customer.
 * @param order_id Cloud-generated order UUID.
 * @param order_number Human-readable order code (e.g. ORD-20261005-A1B2).
 * @param amount_paise Total price in smallest currency unit (paise).
 * @param upi_payload Dynamic UPI deep link string.
 * @param timeout_sec Expiration countdown duration (default 180s).
 * @return 0 on success, negative error code on failure.
 */
int qr_payment_start_session(
    uint8_t slot_number,
    const char *order_id,
    const char *order_number,
    uint32_t amount_paise,
    const char *upi_payload,
    uint16_t timeout_sec
);

/**
 * @brief Periodic driver tick handler updating countdown timer and state transitions.
 * @param delta_ms Elapsed milliseconds since last tick (e.g. 100ms or 1000ms).
 * @return True if session is currently active and displaying.
 */
bool qr_payment_process_tick(uint32_t delta_ms);

/**
 * @brief Cancel active QR session (e.g. customer pressed Cancel or inserted physical coins).
 * @param reason Reason for cancellation (e.g. "USER_CANCELLED", "COIN_INSERTED").
 */
void qr_payment_cancel_session(const char *reason);

/**
 * @brief Determine if a dynamic QR payment session is currently in progress.
 */
bool qr_payment_is_active(void);

/**
 * @brief Get remaining seconds before active QR payment expires.
 */
int32_t qr_payment_get_seconds_remaining(void);

/**
 * @brief Get a copy of the active session state and payload.
 * @param out_session Pointer to destination struct.
 * @return 0 if session retrieved, -1 if no active session.
 */
int qr_payment_get_session(qr_payment_session_t *out_session);

/**
 * @brief Mark the active QR payment session as authorized by cloud webhook.
 * @param dispense_token Cryptographically signed token from cloud authorizing dispense.
 * @return 0 on success, -1 if no matching active session.
 */
int qr_payment_set_authorized(const char *dispense_token);

/**
 * @brief Generate a simplified text-based QR frame preview for debugging/logging.
 * @param out_buf Buffer to store ASCII preview.
 * @param max_len Size of destination buffer.
 */
void qr_payment_render_ascii_preview(char *out_buf, size_t max_len);

#ifdef __cplusplus
}
#endif

#endif /* QR_PAYMENT_H */
