/*
 * Copyright (c) 2024 PulseScope Contributors
 *
 * SPDX-License-Identifier: MIT
 */

/**
 * @file usb_cdc.h
 * @brief USB CDC-ACM transport layer using TinyUSB
 *
 * Provides frame-oriented send/receive over USB CDC.
 * Handles framing, CRC, and retransmission.
 */
#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

// ============================================================================
// Transport Callbacks
// ============================================================================
typedef void (*usb_on_frame_t)(uint8_t type, const uint8_t *payload, uint16_t len, void *ctx);
typedef void (*usb_on_error_t)(ps_error_e error, void *ctx);

// ============================================================================
// Public API
// ============================================================================

/**
 * @brief Initialize USB CDC stack (TinyUSB)
 */
ps_error_e usb_cdc_init(void);

/**
 * @brief Register frame and error callbacks
 */
void usb_cdc_set_callbacks(usb_on_frame_t on_frame, usb_on_error_t on_error, void *ctx);

/**
 * @brief Send a frame (async, queues for TinyUSB Task)
 */
ps_error_e usb_cdc_send_frame(uint8_t type, const void *payload, uint16_t len);

/**
 * @brief Send ACK/NACK for a command
 */
ps_error_e usb_cdc_send_ack(uint8_t cmd_type, ps_error_e status);

/**
 * @brief Send data chunk (high-throughput path, minimal overhead)
 */
ps_error_e usb_cdc_send_data_chunk(uint16_t sequence, uint32_t timestamp_us,
                                    uint32_t sample_count, const uint8_t *samples, uint16_t flags);

/**
 * @brief Send trigger hit event
 */
ps_error_e usb_cdc_send_trigger_hit(uint32_t sample_index, uint32_t timestamp_us, uint8_t source);

/**
 * @brief Send capture done event
 */
ps_error_e usb_cdc_send_capture_done(uint32_t total_samples, uint32_t duration_us,
                                      uint16_t chunks_sent, uint8_t status);

/**
 * @brief Send error event
 */
ps_error_e usb_cdc_send_error(ps_error_e code, const char *message);

/**
 * @brief Process incoming USB data (call from main loop or dedicated task)
 */
void usb_cdc_task(void *arg);

/**
 * @brief Check if USB is connected and configured
 */
bool usb_cdc_is_connected(void);

/**
 * @brief Get TX queue depth (for flow control)
 */
size_t usb_cdc_get_tx_depth(void);

/**
 * @brief Flush TX queue (blocking, with timeout)
 */
ps_error_e usb_cdc_flush(uint32_t timeout_ms);

#ifdef __cplusplus
}
#endif