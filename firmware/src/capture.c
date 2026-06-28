/*
 * Copyright (c) 2024 PulseScope Contributors
 *
 * SPDX-License-Identifier: MIT
 */

/**
 * @file capture.c
 * @brief DMA-based 4-channel logic capture using ESP32-S3 I2S parallel mode
 *
 * Architecture:
 * - I2S0 in LCD/Camera mode (parallel input)
 * - 4 GPIO pins mapped to I2S data lines
 * - Double-buffered DMA with ping-pong buffers
 * - FreeRTOS task feeds USB ring buffer
 */
#include "capture.h"
#include "trigger.h"
#include "usb_cdc.h"
#include "ringbuffer.h"
#include "driver/i2s.h"
#include "driver/gpio.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include <string.h>

static const char *TAG = "CAPTURE";

// ============================================================================
// Internal State
// ============================================================================
typedef struct {
    capture_config_t config;
    capture_chunk_cb_t chunk_cb;
    capture_event_cb_t event_cb;
    void *user_ctx;

    // DMA buffers (ping-pong)
    uint8_t *dma_buf_a;
    uint8_t *dma_buf_b;
    size_t dma_buf_size;

    // State
    capture_state_e state;
    capture_stats_t stats;
    SemaphoreHandle_t state_mutex;

    // I2S
    i2s_chan_handle_t rx_handle;
    i2s_chan_config_t chan_cfg;

    // Timing
    uint32_t actual_sample_rate_hz;
    uint64_t capture_start_us;
} capture_ctx_t;

static capture_ctx_t s_ctx = {0};

// ============================================================================
// Helpers
// ============================================================================
static inline void set_state(capture_state_e new_state) {
    xSemaphoreTake(s_ctx.state_mutex, portMAX_DELAY);
    if (s_ctx.state != new_state) {
        ESP_LOGI(TAG, "State: %d -> %d", s_ctx.state, new_state);
        s_ctx.state = new_state;
        if (s_ctx.event_cb) {
            s_ctx.event_cb(new_state, s_ctx.user_ctx);
        }
    }
    xSemaphoreGive(s_ctx.state_mutex);
}

static inline void increment_overrun(void) {
    s_ctx.stats.overrun_count++;
}

static inline void add_samples(uint32_t count) {
    s_ctx.stats.samples_captured += count;
}

// ============================================================================
// I2S DMA Configuration
// ============================================================================
static ps_error_e configure_i2s(uint32_t sample_rate_hz) {
    i2s_chan_config_t chan_cfg = {
        .id = CAPTURE_I2S_PORT,
        .role = I2S_ROLE_MASTER,
        .dma_desc_num = CAPTURE_DMA_BUF_COUNT,
        .dma_frame_num = CAPTURE_DMA_BUF_LEN,
        .auto_clear = false,
    };
    ESP_ERROR_CHECK(i2s_new_channel(&chan_cfg, NULL, &s_ctx.rx_handle));

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(sample_rate_hz),
        .slot_cfg = I2S_STD_MSB_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = CAPTURE_GPIO_CLK,
            .ws = I2S_GPIO_UNUSED,
            .dout = I2S_GPIO_UNUSED,
            .din = I2S_GPIO_UNUSED,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };

    std_cfg.slot_cfg.slot_mode = I2S_SLOT_MODE_STEREO;
    std_cfg.slot_cfg.slot_mask = I2S_STD_SLOT_BOTH;
    std_cfg.slot_cfg.data_bit_width = I2S_DATA_BIT_WIDTH_16BIT;
    std_cfg.slot_cfg.ws_width = 8;

    ESP_ERROR_CHECK(i2s_channel_init_std_mode(s_ctx.rx_handle, &std_cfg));

    s_ctx.actual_sample_rate_hz = sample_rate_hz;
    return PS_OK;
}

static void free_i2s(void) {
    if (s_ctx.rx_handle) {
        i2s_del_channel(s_ctx.rx_handle);
        s_ctx.rx_handle = NULL;
    }
}

// ============================================================================
// DMA Buffer Allocation
// ============================================================================
static ps_error_e alloc_dma_buffers(void) {
    s_ctx.dma_buf_size = CAPTURE_DMA_BUF_COUNT * CAPTURE_DMA_BUF_LEN * 4;

    s_ctx.dma_buf_a = heap_caps_malloc(s_ctx.dma_buf_size, MALLOC_CAP_DMA | MALLOC_CAP_8BIT);
    s_ctx.dma_buf_b = heap_caps_malloc(s_ctx.dma_buf_size, MALLOC_CAP_DMA | MALLOC_CAP_8BIT);

    if (!s_ctx.dma_buf_a || !s_ctx.dma_buf_b) {
        ESP_LOGE(TAG, "Failed to allocate DMA buffers");
        return PS_ERR_MEMORY;
    }

    ESP_LOGI(TAG, "DMA buffers: %zu bytes each", s_ctx.dma_buf_size);
    return PS_OK;
}

static void free_dma_buffers(void) {
    if (s_ctx.dma_buf_a) {
        heap_caps_free(s_ctx.dma_buf_a);
        s_ctx.dma_buf_a = NULL;
    }
    if (s_ctx.dma_buf_b) {
        heap_caps_free(s_ctx.dma_buf_b);
        s_ctx.dma_buf_b = NULL;
    }
}

// ============================================================================
// GPIO Configuration
// ============================================================================
static ps_error_e configure_gpio(void) {
    gpio_config_t io_conf = {
        .pin_bit_mask = (1ULL << CAPTURE_GPIO_CH0) |
                        (1ULL << CAPTURE_GPIO_CH1) |
                        (1ULL << CAPTURE_GPIO_CH2) |
                        (1ULL << CAPTURE_GPIO_CH3),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&io_conf));

    ESP_LOGI(TAG, "GPIO configured for capture");
    return PS_OK;
}

// ============================================================================
// Capture Task
// ============================================================================
static void capture_task(void *arg) {
    (void)arg;
    static uint8_t *current_buf = NULL;
    static uint8_t *next_buf = NULL;

    current_buf = s_ctx.dma_buf_a;
    next_buf = s_ctx.dma_buf_b;

    size_t bytes_read = 0;
    uint16_t chunk_seq = 0;
    uint32_t total_samples = 0;

    while (s_ctx.state == CAP_STATE_ARMED || s_ctx.state == CAP_STATE_TRIGGERED) {
        esp_err_t ret = i2s_channel_read(s_ctx.rx_handle, current_buf, s_ctx.dma_buf_size,
                                         &bytes_read, 100 / portTICK_PERIOD_MS);

        if (ret != ESP_OK) {
            if (ret == ESP_ERR_TIMEOUT) continue;
            ESP_LOGE(TAG, "I2S read error: %s", esp_err_to_name(ret));
            set_state(CAP_STATE_ERROR);
            s_ctx.stats.error_code = ret;
            break;
        }

        if (bytes_read == 0) continue;

        uint32_t samples = bytes_read / 4;
        if (samples == 0) continue;

        add_samples(samples);
        total_samples += samples;

        if (s_ctx.state == CAP_STATE_ARMED) {
            if (trigger_process(current_buf, samples, total_samples - samples)) {
                set_state(CAP_STATE_TRIGGERED);
            }
        }

        if (s_ctx.chunk_cb) {
            s_ctx.chunk_cb(current_buf, bytes_read, s_ctx.user_ctx);
        }

        usb_cdc_send_data_chunk(chunk_seq++, esp_timer_get_time(),
                                 samples, current_buf,
                                 (s_ctx.state == CAP_STATE_TRIGGERED) ? 0x02 : 0x00);

        s_ctx.stats.chunks_sent++;

        if (s_ctx.config.target_samples > 0 && total_samples >= s_ctx.config.target_samples) {
            set_state(CAP_STATE_DONE);
            break;
        }

        uint8_t *tmp = current_buf;
        current_buf = next_buf;
        next_buf = tmp;
    }

    usb_cdc_flush(1000);
    vTaskDelete(NULL);
}

// ============================================================================
// Public API Implementation
// ============================================================================
ps_error_e capture_init(void) {
    memset(&s_ctx, 0, sizeof(s_ctx));
    s_ctx.state_mutex = xSemaphoreCreateMutex();
    if (!s_ctx.state_mutex) return PS_ERR_MEMORY;

    ESP_ERROR_CHECK(configure_gpio());

    ESP_LOGI(TAG, "Capture initialized");
    return PS_OK;
}

void capture_deinit(void) {
    capture_stop();
    free_i2s();
    free_dma_buffers();
    if (s_ctx.state_mutex) {
        vSemaphoreDelete(s_ctx.state_mutex);
        s_ctx.state_mutex = NULL;
    }
}

ps_error_e capture_start(const capture_config_t *config,
                         capture_chunk_cb_t chunk_cb,
                         capture_event_cb_t event_cb,
                         void *user_ctx) {
    if (s_ctx.state != CAP_STATE_IDLE) return PS_ERR_BUSY;
    if (!config) return PS_ERR_INVALID_ARG;

    memcpy(&s_ctx.config, config, sizeof(*config));
    s_ctx.chunk_cb = chunk_cb;
    s_ctx.event_cb = event_cb;
    s_ctx.user_ctx = user_ctx;

    memset(&s_ctx.stats, 0, sizeof(s_ctx.stats));

    ps_error_e err = alloc_dma_buffers();
    if (err != PS_OK) return err;

    err = configure_i2s(config->sample_rate_hz);
    if (err != PS_OK) {
        free_dma_buffers();
        return err;
    }

    trigger_config_t trig_cfg = {
        .mode = config->trigger_mode,
        .channel = config->trigger_channel,
        .active_channels = config->active_channels,
        .edge = config->trigger_edge,
        .pulse_polarity = config->trigger_pulse_min_ns ? PS_PULSE_POSITIVE : PS_PULSE_EITHER,
        .pulse_min_ns = config->trigger_pulse_min_ns,
        .pulse_max_ns = config->trigger_pulse_max_ns,
        .pattern_mask = config->trigger_pattern & 0xF,
        .pattern_value = (config->trigger_pattern >> 4) & 0xF,
        .pretrigger_samples = config->pretrigger_samples,
    };
    trigger_arm(&trig_cfg, s_ctx.actual_sample_rate_hz);

    s_ctx.capture_start_us = esp_timer_get_time();
    set_state(CAP_STATE_ARMED);

    BaseType_t ret = xTaskCreatePinnedToCore(capture_task, "capture", 4096, NULL,
                                              configMAX_PRIORITIES - 1, NULL, 0);
    if (ret != pdPASS) {
        set_state(CAP_STATE_ERROR);
        s_ctx.stats.error_code = ESP_ERR_NO_MEM;
        return PS_ERR_MEMORY;
    }

    return PS_OK;
}

ps_error_e capture_stop(void) {
    if (s_ctx.state == CAP_STATE_IDLE) return PS_OK;

    trigger_disarm();
    free_i2s();
    free_dma_buffers();
    set_state(CAP_STATE_IDLE);
    return PS_OK;
}

void capture_get_stats(capture_stats_t *stats) {
    if (stats) {
        xSemaphoreTake(s_ctx.state_mutex, portMAX_DELAY);
        *stats = s_ctx.stats;
        xSemaphoreGive(s_ctx.state_mutex);
    }
}

bool capture_is_active(void) {
    capture_state_e state;
    xSemaphoreTake(s_ctx.state_mutex, portMAX_DELAY);
    state = s_ctx.state;
    xSemaphoreGive(s_ctx.state_mutex);
    return state == CAP_STATE_ARMED || state == CAP_STATE_TRIGGERED;
}

ps_error_e capture_get_actual_rate(uint32_t requested_hz, uint32_t *actual_hz) {
    if (requested_hz > CAPTURE_MAX_SAMPLE_RATE_HZ) requested_hz = CAPTURE_MAX_SAMPLE_RATE_HZ;
    if (requested_hz < CAPTURE_MIN_SAMPLE_RATE_HZ) requested_hz = CAPTURE_MIN_SAMPLE_RATE_HZ;
    *actual_hz = requested_hz;
    return PS_OK;
}

ps_error_e capture_self_test(void) {
    ps_error_e err = configure_i2s(1000000);
    if (err == PS_OK) {
        free_i2s();
    }
    return err;
}