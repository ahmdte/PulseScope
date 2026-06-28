/*
 * Copyright (c) 2024 PulseScope Contributors
 *
 * SPDX-License-Identifier: MIT
 */

/**
 * @file capture.h
 * @brief DMA-based 4-channel logic capture engine
 */
#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

// ============================================================================
// Configuration
// ============================================================================
#define CAPTURE_MAX_SAMPLE_RATE_HZ     20000000  // 20 MS/s
#define CAPTURE_MIN_SAMPLE_RATE_HZ     1000
#define CAPTURE_MAX_SAMPLES            524288    // 512K samples (2 MB RAM for 4ch)

// I2S parallel mode pins (fixed by ESP32 hardware)
#define CAPTURE_I2S_PORT               0
#define CAPTURE_GPIO_CH0               12  // I2S0_DATA_IN0
#define CAPTURE_GPIO_CH1               13  // I2S0_DATA_IN1
#define CAPTURE_GPIO_CH2               14  // I2S0_DATA_IN2
#define CAPTURE_GPIO_CH3               15  // I2S0_DATA_IN3
#define CAPTURE_GPIO_CLK               4   // I2S0_CLK_IN (external clock) or internal

// DMA buffer tuning
#define CAPTURE_DMA_BUF_COUNT          8
#define CAPTURE_DMA_BUF_LEN            256     // Samples per buffer (per channel)

// ============================================================================
// Data Structures
// ============================================================================
typedef struct {
    uint32_t sample_rate_hz;
    uint32_t target_samples;
    uint32_t pretrigger_samples;
    uint8_t  active_channels;     // Bitmask
    uint8_t  trigger_mode;
    uint8_t  trigger_channel;
    uint8_t  trigger_edge;
    uint32_t trigger_pattern;
    uint32_t trigger_pulse_min_ns;
    uint32_t trigger_pulse_max_ns;
} capture_config_t;

typedef enum {
    CAP_STATE_IDLE     = 0,
    CAP_STATE_ARMED    = 1,
    CAP_STATE_TRIGGERED= 2,
    CAP_STATE_DONE     = 3,
    CAP_STATE_ERROR    = 4,
} capture_state_e;

typedef struct {
    capture_state_e state;
    uint32_t samples_captured;
    uint32_t chunks_sent;
    uint32_t trigger_index;
    uint32_t overrun_count;
    uint32_t error_code;
} capture_stats_t;

// Callbacks
typedef void (*capture_chunk_cb_t)(const uint8_t *data, size_t len, void *user_ctx);
typedef void (*capture_event_cb_t)(capture_state_e state, void *user_ctx);

// ============================================================================
// Public API
// ============================================================================

/**
 * @brief Initialize capture subsystem (I2S + DMA)
 * @return PS_OK on success
 */
ps_error_e capture_init(void);

/**
 * @brief Deinitialize capture subsystem
 */
void capture_deinit(void);

/**
 * @brief Configure and arm capture
 * @param config Capture configuration
 * @param chunk_cb Callback for each data chunk ready
 * @param event_cb Callback for state changes
 * @param user_ctx User context passed to callbacks
 * @return PS_OK on success
 */
ps_error_e capture_start(const capture_config_t *config,
                          capture_chunk_cb_t chunk_cb,
                          capture_event_cb_t event_cb,
                          void *user_ctx);

/**
 * @brief Stop capture immediately
 */
ps_error_e capture_stop(void);

/**
 * @brief Get current capture state and statistics
 */
void capture_get_stats(capture_stats_t *stats);

/**
 * @brief Check if capture is active (armed or triggered)
 */
bool capture_is_active(void);

/**
 * @brief Get actual achievable sample rate for requested rate
 * @param requested_hz Requested sample rate
 * @param actual_hz [out] Actual sample rate that will be used
 * @return PS_OK on success
 */
ps_error_e capture_get_actual_rate(uint32_t requested_hz, uint32_t *actual_hz);

/**
 * @brief Self-test: generate internal pattern, capture, verify
 * @return PS_OK if test passes
 */
ps_error_e capture_self_test(void);

#ifdef __cplusplus
}
#endif