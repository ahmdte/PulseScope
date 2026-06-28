/*
 * Copyright (c) 2024 PulseScope Contributors
 *
 * SPDX-License-Identifier: MIT
 */

/**
 * @file trigger.c
 * @brief Real-time trigger evaluation engine
 *
 * Processes incoming sample buffers from DMA, evaluates trigger conditions.
 * Runs in capture task context (no separate task needed).
 */
#include "trigger.h"
#include "capture.h"
#include <string.h>

static const char *TAG = "TRIGGER";

// ============================================================================
// Internal State
// ============================================================================
typedef struct {
    trigger_config_t config;
    trigger_state_e state;
    uint32_t trigger_index;
    uint32_t samples_since_trigger;
    uint32_t sample_rate_hz;

    // For pulse-width detection
    uint32_t last_edge_idx[4];
    uint8_t  last_level[4];
} trigger_ctx_t;

static trigger_ctx_t s_ctx = {0};

// ============================================================================
// Helpers
// ============================================================================
static inline uint8_t get_channel_bit(const uint8_t *sample, uint8_t channel) {
    return (sample[0] >> channel) & 0x01;
}

static inline uint8_t get_sample_channels(const uint8_t *sample) {
    return sample[0] & 0x0F;
}

// ============================================================================
// Trigger Evaluation Functions
// ============================================================================
static bool check_edge_trigger(const uint8_t *samples, uint32_t num_samples,
                                uint32_t *out_offset) {
    uint8_t prev = get_sample_channels(samples);
    if (s_ctx.last_level[s_ctx.config.channel] != 0xFF) {
        prev = s_ctx.last_level[s_ctx.config.channel];
    }

    for (uint32_t i = 0; i < num_samples; i++) {
        uint8_t curr = get_channel_bit(&samples[i], s_ctx.config.channel);

        bool edge_detected = false;
        switch (s_ctx.config.edge) {
            case PS_TRIG_EDGE_RISING:
                edge_detected = (prev == 0 && curr == 1);
                break;
            case PS_TRIG_EDGE_FALLING:
                edge_detected = (prev == 1 && curr == 0);
                break;
            case PS_TRIG_EDGE_EITHER:
                edge_detected = (prev != curr);
                break;
        }

        if (edge_detected) {
            if (out_offset) *out_offset = i;
            return true;
        }
        prev = curr;
    }

    s_ctx.last_level[s_ctx.config.channel] = prev;
    return false;
}

static bool check_pulse_trigger(const uint8_t *samples, uint32_t num_samples,
                                 uint32_t buffer_start_idx, uint32_t *out_offset) {
    uint8_t ch = s_ctx.config.channel;
    bool polarity = (s_ctx.config.pulse_polarity == PS_PULSE_POSITIVE);
    uint32_t min_samples = (s_ctx.config.pulse_min_ns * s_ctx.sample_rate_hz) / 1000000000ULL;
    uint32_t max_samples = (s_ctx.config.pulse_max_ns * s_ctx.sample_rate_hz) / 1000000000ULL;

    if (s_ctx.last_edge_idx[ch] == 0xFFFFFFFF) {
        s_ctx.last_edge_idx[ch] = buffer_start_idx;
    }

    uint8_t prev = get_channel_bit(samples + num_samples - 1, ch);
    if (num_samples > 0) {
        prev = get_channel_bit(samples, ch);
    }

    for (uint32_t i = 0; i < num_samples; i++) {
        uint8_t curr = get_channel_bit(&samples[i], ch);
        bool rising = (prev == 0 && curr == 1);
        bool falling = (prev == 1 && curr == 0);

        if ((polarity && rising) || (!polarity && falling) ||
            s_ctx.config.pulse_polarity == PS_PULSE_EITHER) {
            uint32_t width = (buffer_start_idx + i) - s_ctx.last_edge_idx[ch];
            if (width >= min_samples && width <= max_samples) {
                if (out_offset) *out_offset = (width / 2);
                return true;
            }
            s_ctx.last_edge_idx[ch] = buffer_start_idx + i;
        }
        prev = curr;
    }

    return false;
}

static bool check_pattern_trigger(const uint8_t *samples, uint32_t num_samples,
                                   uint32_t *out_offset) {
    uint8_t mask = s_ctx.config.pattern_mask;
    uint8_t value = s_ctx.config.pattern_value;

    for (uint32_t i = 0; i < num_samples; i++) {
        uint8_t chans = get_sample_channels(&samples[i]);
        if ((chans & mask) == value) {
            if (out_offset) *out_offset = i;
            return true;
        }
    }
    return false;
}

// ============================================================================
// Public API
// ============================================================================
ps_error_e trigger_init(void) {
    memset(&s_ctx, 0, sizeof(s_ctx));
    s_ctx.state = TRIG_STATE_WAITING;
    s_ctx.trigger_index = 0xFFFFFFFF;
    for (int i = 0; i < 4; i++) {
        s_ctx.last_edge_idx[i] = 0xFFFFFFFF;
        s_ctx.last_level[i] = 0xFF;
    }
    return PS_OK;
}

ps_error_e trigger_arm(const trigger_config_t *config, uint32_t sample_rate_hz) {
    if (!config) return PS_ERR_INVALID_ARG;

    memcpy(&s_ctx.config, config, sizeof(s_ctx.config));
    s_ctx.sample_rate_hz = sample_rate_hz;
    s_ctx.state = TRIG_STATE_WAITING;
    s_ctx.trigger_index = 0xFFFFFFFF;
    s_ctx.samples_since_trigger = 0;

    for (int i = 0; i < 4; i++) {
        s_ctx.last_edge_idx[i] = 0xFFFFFFFF;
        s_ctx.last_level[i] = 0xFF;
    }

    ESP_LOGI(TAG, "Trigger armed: mode=%d, ch=%d", config->mode, config->channel);
    return PS_OK;
}

bool trigger_process(const uint8_t *samples, uint32_t num_samples,
                     uint32_t buffer_start_idx) {
    if (s_ctx.state != TRIG_STATE_WAITING) return false;

    uint32_t trigger_offset = 0;
    bool fired = false;

    switch (s_ctx.config.mode) {
        case PS_TRIG_EDGE:
            fired = check_edge_trigger(samples, num_samples, &trigger_offset);
            break;
        case PS_TRIG_PULSE:
            fired = check_pulse_trigger(samples, num_samples, buffer_start_idx, &trigger_offset);
            break;
        case PS_TRIG_PATTERN:
            fired = check_pattern_trigger(samples, num_samples, &trigger_offset);
            break;
        default:
            return false;
    }

    if (fired) {
        s_ctx.trigger_index = buffer_start_idx + trigger_offset;
        s_ctx.state = TRIG_STATE_FIRED;
        ESP_LOGI(TAG, "Trigger fired at sample %u", s_ctx.trigger_index);
        return true;
    }

    return false;
}

void trigger_get_status(trigger_status_t *status) {
    if (status) {
        status->state = s_ctx.state;
        status->trigger_index = s_ctx.trigger_index;
        status->samples_since_trigger = s_ctx.samples_since_trigger;
    }
}

void trigger_disarm(void) {
    s_ctx.state = TRIG_STATE_WAITING;
    s_ctx.trigger_index = 0xFFFFFFFF;
    s_ctx.samples_since_trigger = 0;
}

bool trigger_check_buffer(const trigger_config_t *config,
                          const uint8_t *samples,
                          uint32_t num_samples,
                          uint32_t *out_trigger_offset) {
    trigger_config_t saved = s_ctx.config;
    if (config) s_ctx.config = *config;

    bool result = false;
    uint32_t offset = 0;

    switch (s_ctx.config.mode) {
        case PS_TRIG_EDGE:
            result = check_edge_trigger(samples, num_samples, &offset);
            break;
        case PS_TRIG_PULSE:
            result = check_edge_trigger(samples, num_samples, &offset);
            break;
        case PS_TRIG_PATTERN:
            result = check_pattern_trigger(samples, num_samples, &offset);
            break;
        default:
            break;
    }

    if (result && out_trigger_offset) *out_trigger_offset = offset;
    s_ctx.config = saved;
    return result;
}