/*
 * Copyright (c) 2024 PulseScope Contributors
 *
 * SPDX-License-Identifier: MIT
 */

/**
 * @file trigger.h
 * @brief Real-time trigger evaluation engine
 *
 * Runs in capture task context, evaluates trigger conditions on incoming DMA buffers.
 * Supports edge, pulse-width, pattern, and protocol triggers.
 */
#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

// ============================================================================
// Trigger Configuration
// ============================================================================
typedef struct {
    ps_trigger_mode_e mode;
    uint8_t channel;              // 0-3 for single-channel triggers
    uint8_t active_channels;      // Bitmask for pattern trigger

    // Edge trigger
    ps_trigger_edge_e edge;

    // Pulse-width trigger
    ps_pulse_polarity_e pulse_polarity;
    uint32_t pulse_min_ns;
    uint32_t pulse_max_ns;

    // Pattern trigger (4-bit mask + value)
    uint8_t pattern_mask;
    uint8_t pattern_value;

    // Protocol triggers (future)
    uint32_t uart_baud;
    uint8_t  uart_data_bits;

    // Pre-trigger samples to keep
    uint32_t pretrigger_samples;
} trigger_config_t;

typedef enum {
    TRIG_STATE_WAITING  = 0,
    TRIG_STATE_FIRED    = 1,
    TRIG_STATE_POST     = 2,  // Collecting post-trigger samples
    TRIG_STATE_DONE     = 3,
} trigger_state_e;

typedef struct {
    trigger_state_e state;
    uint32_t trigger_index;     // Absolute sample index where trigger fired
    uint32_t samples_since_trigger;
} trigger_status_t;

// ============================================================================
// Public API
// ============================================================================

/**
 * @brief Initialize trigger engine (call once at startup)
 */
ps_error_e trigger_init(void);

/**
 * @brief Configure and arm trigger engine
 * @param config Trigger configuration
 * @param sample_rate_hz Sample rate in Hz (for pulse-width timing)
 * @return PS_OK on success
 */
ps_error_e trigger_arm(const trigger_config_t *config, uint32_t sample_rate_hz);

/**
 * @brief Process a block of samples from DMA
 *
 * Called from capture task for each DMA buffer.
 * Evaluates trigger condition on incoming data.
 *
 * @param samples Pointer to packed samples (4 channels, 1 bit each)
 * @param num_samples Number of 4-channel samples in buffer
 * @param buffer_start_idx Absolute sample index of first sample in buffer
 * @return true if trigger fired during this buffer
 */
bool trigger_process(const uint8_t *samples, uint32_t num_samples, uint32_t buffer_start_idx);

/**
 * @brief Get current trigger status
 */
void trigger_get_status(trigger_status_t *status);

/**
 * @brief Disarm trigger engine
 */
void trigger_disarm(void);

/**
 * @brief Offline check - test if buffer contains trigger (no state change)
 * @param config Trigger configuration
 * @param samples Sample buffer to check
 * @param num_samples Number of samples in buffer
 * @param out_trigger_offset [out] Offset within buffer where trigger occurred
 * @return true if trigger condition met
 */
bool trigger_check_buffer(const trigger_config_t *config,
                           const uint8_t *samples,
                           uint32_t num_samples,
                           uint32_t *out_trigger_offset);

#ifdef __cplusplus
}
#endif