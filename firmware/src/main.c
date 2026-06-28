/*
 * Copyright (c) 2024 PulseScope Contributors
 *
 * SPDX-License-Identifier: MIT
 */

/**
 * @file main.c
 * @brief PulseScope firmware entry point
 *
 * Initializes subsystems, handles command processing, manages capture state.
 */
#include "capture.h"
#include "trigger.h"
#include "usb_cdc.h"
#include "protocol.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "driver/gpio.h"
#include <string.h>

static const char *TAG = "MAIN";

// ============================================================================
// Command Handlers
// ============================================================================
static void handle_command(uint8_t type, const uint8_t *payload, uint16_t len, void *ctx) {
    ps_error_e err = PS_OK;
    (void)ctx;

    switch (type) {
        case PS_CMD_START: {
            if (len < sizeof(ps_cmd_start_t)) {
                err = PS_ERR_INVALID_ARG;
                break;
            }
            const ps_cmd_start_t *cmd = (const ps_cmd_start_t *)payload;

            capture_config_t cap_cfg = {
                .sample_rate_hz = cmd->sample_rate_hz,
                .target_samples = cmd->num_samples,
                .pretrigger_samples = cmd->pretrigger_samples,
                .active_channels = 0x0F,
                .trigger_mode = cmd->trigger_mode,
                .trigger_channel = cmd->trigger_channel,
                .trigger_edge = cmd->trigger_edge,
                .trigger_pattern = cmd->trigger_pattern,
                .trigger_pulse_min_ns = cmd->trigger_pulse_min_ns,
                .trigger_pulse_max_ns = cmd->trigger_pulse_max_ns,
            };

            err = capture_start(&cap_cfg, NULL, NULL, NULL);
            break;
        }

        case PS_CMD_STOP: {
            err = capture_stop();
            break;
        }

        case PS_CMD_CONFIG: {
            if (len < sizeof(ps_cmd_config_t)) {
                err = PS_ERR_INVALID_ARG;
                break;
            }
            break;
        }

        case PS_CMD_GET_INFO: {
            ps_evt_info_t info = {
                .protocol_version = PS_PROTOCOL_VERSION,
                .hw_version_major = 1,
                .hw_version_minor = 0,
                .hw_version_patch = 0,
                .fw_version = 0x010000,
                .max_sample_rate_hz = CAPTURE_MAX_SAMPLE_RATE_HZ,
                .max_samples = CAPTURE_MAX_SAMPLES,
                .num_channels = 4,
                .capabilities = PS_DEFAULT_CAPABILITIES,
            };
            strncpy(info.device_name, "PulseScope", sizeof(info.device_name) - 1);

            usb_cdc_send_frame(PS_EVT_INFO, &info, sizeof(info));
            return;
        }

        case PS_CMD_SELF_TEST: {
            err = capture_self_test();
            break;
        }

        case PS_CMD_PING: {
            usb_cdc_send_frame(PS_EVT_PONG, NULL, 0);
            return;
        }

        default:
            err = PS_ERR_PROTOCOL;
            break;
    }

    if (type != PS_CMD_GET_INFO && type != PS_CMD_PING) {
        usb_cdc_send_ack(type, err);
    }
}

// ============================================================================
// Capture Callbacks
// ============================================================================
static void capture_chunk_cb(const uint8_t *data, size_t len, void *ctx) {
    (void)data; (void)len; (void)ctx;
}

static void capture_event_cb(capture_state_e state, void *ctx) {
    (void)ctx;
    switch (state) {
        case CAP_STATE_DONE: {
            capture_stats_t stats;
            capture_get_stats(&stats);
            usb_cdc_send_capture_done(stats.samples_captured,
                                       esp_timer_get_time(),
                                       stats.chunks_sent, 0);
            break;
        }
        case CAP_STATE_ERROR: {
            capture_stats_t stats;
            capture_get_stats(&stats);
            usb_cdc_send_error(stats.error_code, "Capture error");
            break;
        }
        default:
            break;
    }
}

// ============================================================================
// Main Task
// ============================================================================
static void main_task(void *arg) {
    (void)arg;

    xTaskCreatePinnedToCore(usb_cdc_task, "usb_cdc", 4096, NULL,
                            configMAX_PRIORITIES - 2, NULL, 1);

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(1000));
        ESP_LOGI(TAG, "Heap free: %zu", esp_get_free_heap_size());
    }
}

// ============================================================================
// App Entry
// ============================================================================
void app_main(void) {
    ESP_LOGI(TAG, "PulseScope v1.0.0 starting...");

    ESP_ERROR_CHECK(capture_init());
    ESP_ERROR_CHECK(trigger_init());
    ESP_ERROR_CHECK(usb_cdc_init());

    usb_cdc_set_callbacks(handle_command, NULL, NULL);

    xTaskCreatePinnedToCore(main_task, "main", 4096, NULL,
                            configMAX_PRIORITIES - 3, NULL, 1);

    ESP_LOGI(TAG, "PulseScope ready");
}