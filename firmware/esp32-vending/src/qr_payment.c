/**
 * @file qr_payment.c
 * @brief Dynamic UPI QR Payment Display Engine & Countdown Timer for ESP32 Vending
 */

#include "qr_payment.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#define TAG "QR_PAYMENT"
#define LOGI(...) printf("[INFO] " TAG ": " __VA_ARGS__); printf("\n")
#define LOGW(...) printf("[WARN] " TAG ": " __VA_ARGS__); printf("\n")
#define LOGE(...) printf("[ERROR] " TAG ": " __VA_ARGS__); printf("\n")

static qr_payment_session_t s_session;
static bool s_initialized = false;
static uint32_t s_accumulated_tick_ms = 0;

int qr_payment_init(void) {
    memset(&s_session, 0, sizeof(qr_payment_session_t));
    s_session.state = QR_PAYMENT_STATE_IDLE;
    s_accumulated_tick_ms = 0;
    s_initialized = true;

    LOGI("Dynamic QR Payment Subsystem initialized.");
    return 0;
}

int qr_payment_start_session(
    uint8_t slot_number,
    const char *order_id,
    const char *order_number,
    uint32_t amount_paise,
    const char *upi_payload,
    uint16_t timeout_sec
) {
    if (!order_id || !upi_payload) {
        return -1;
    }

    memset(&s_session, 0, sizeof(qr_payment_session_t));
    s_session.slot_number = slot_number;
    strncpy(s_session.order_id, order_id, sizeof(s_session.order_id) - 1);
    if (order_number) {
        strncpy(s_session.order_number, order_number, sizeof(s_session.order_number) - 1);
    }
    s_session.amount_paise = amount_paise;
    strncpy(s_session.upi_payload, upi_payload, sizeof(s_session.upi_payload) - 1);

    s_session.timeout_seconds = (timeout_sec > 0) ? timeout_sec : QR_DEFAULT_TIMEOUT_SEC;
    s_session.seconds_remaining = s_session.timeout_seconds;
    s_session.state = QR_PAYMENT_STATE_DISPLAYING;
    s_accumulated_tick_ms = 0;

    LOGI("Started dynamic QR session for Order '%s' (Slot %u, Price: ₹%.2f, Timeout: %us)",
         s_session.order_number, slot_number, amount_paise / 100.0, s_session.timeout_seconds);

    return 0;
}

bool qr_payment_process_tick(uint32_t delta_ms) {
    if (s_session.state != QR_PAYMENT_STATE_DISPLAYING) {
        return false;
    }

    s_accumulated_tick_ms += delta_ms;
    while (s_accumulated_tick_ms >= 1000) {
        s_accumulated_tick_ms -= 1000;
        s_session.seconds_remaining--;

        if (s_session.seconds_remaining <= 0) {
            s_session.seconds_remaining = 0;
            s_session.state = QR_PAYMENT_STATE_EXPIRED;
            LOGW("QR Payment Session for Order '%s' EXPIRED!", s_session.order_number);
            return false;
        }
    }

    return true;
}

void qr_payment_cancel_session(const char *reason) {
    if (s_session.state == QR_PAYMENT_STATE_DISPLAYING) {
        s_session.state = QR_PAYMENT_STATE_CANCELLED;
        LOGI("Dynamic QR Session cancelled (Reason: %s)", reason ? reason : "UNSPECIFIED");
    }
}

bool qr_payment_is_active(void) {
    return (s_session.state == QR_PAYMENT_STATE_DISPLAYING && s_session.seconds_remaining > 0);
}

int32_t qr_payment_get_seconds_remaining(void) {
    if (s_session.state != QR_PAYMENT_STATE_DISPLAYING) {
        return 0;
    }
    return s_session.seconds_remaining;
}

int qr_payment_get_session(qr_payment_session_t *out_session) {
    if (!out_session) return -1;
    memcpy(out_session, &s_session, sizeof(qr_payment_session_t));
    return 0;
}

int qr_payment_set_authorized(const char *dispense_token) {
    if (s_session.state != QR_PAYMENT_STATE_DISPLAYING) {
        LOGW("Cannot authorize QR payment: Session not displaying (current state: %d)", s_session.state);
        return -1;
    }

    s_session.state = QR_PAYMENT_STATE_AUTHORIZED;
    if (dispense_token) {
        strncpy(s_session.dispense_token, dispense_token, sizeof(s_session.dispense_token) - 1);
    }
    LOGI("Payment AUTHORIZED for Order '%s'. Dispense token registered.", s_session.order_number);
    return 0;
}

void qr_payment_render_ascii_preview(char *out_buf, size_t max_len) {
    if (!out_buf || max_len == 0) return;

    if (s_session.state != QR_PAYMENT_STATE_DISPLAYING) {
        snprintf(out_buf, max_len, "[QR DISPLAY IDLE]");
        return;
    }

    snprintf(out_buf, max_len,
             "+---------------------------------------+\n"
             "|         SCAN WITH ANY UPI APP         |\n"
             "|  [QR CODE: ₹%.2f | Slot %02u]          |\n"
             "|  Expires in: %03ds                     |\n"
             "|  Order: %s                 |\n"
             "+---------------------------------------+",
             s_session.amount_paise / 100.0,
             s_session.slot_number,
             (int)s_session.seconds_remaining,
             s_session.order_number);
}
