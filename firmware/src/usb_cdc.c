/*
 * Copyright (c) 2024 PulseScope Contributors
 *
 * SPDX-License-Identifier: MIT
 */

/**
 * @file usb_cdc.c
 * @brief USB CDC-ACM transport using TinyUSB
 *
 * Provides frame-oriented send/receive with CRC validation.
 * Uses ring buffer for high-throughput TX path.
 */
#include "usb_cdc.h"
#include "protocol.h"
#include "ringbuffer.h"
#include "tusb.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include <string.h>

static const char *TAG = "USB_CDC";

// ============================================================================
// Internal State
// ============================================================================
#define USB_CDC_RX_BUF_SIZE    4096
#define USB_CDC_TX_BUF_SIZE    16384

typedef struct {
    usb_on_frame_t on_frame_cb;
    usb_on_error_t on_error_cb;
    void *user_ctx;

    uint8_t rx_buf[USB_CDC_RX_BUF_SIZE];
    size_t rx_len;

    ringbuf_t tx_ring;
    uint8_t tx_ring_buf[USB_CDC_TX_BUF_SIZE];

    SemaphoreHandle_t tx_mutex;
    bool connected;
    bool tinyusb_started;
} usb_cdc_ctx_t;

static usb_cdc_ctx_t s_ctx = {0};

// ============================================================================
// USB Descriptors
// ============================================================================
#define TUSB_DESC_TOTAL_LEN      (TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN)

static const tusb_desc_device_t device_descriptor = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = 0x0200,
    .bDeviceClass = TUSB_CLASS_MISC,
    .bDeviceSubClass = MISC_SUBCLASS_COMMON,
    .bDeviceProtocol = MISC_PROTOCOL_IAD,
    .bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor = 0x303A,
    .idProduct = 0x4001,
    .bcdDevice = 0x0100,
    .iManufacturer = 0x01,
    .iProduct = 0x02,
    .iSerialNumber = 0x03,
    .bNumConfigurations = 1,
};

static const uint8_t config_descriptor[TUSB_DESC_TOTAL_LEN] = {
    0x09, 0x02, TUSB_DESC_TOTAL_LEN & 0xFF, (TUSB_DESC_TOTAL_LEN >> 8) & 0xFF,
    0x02, 0x01, 0x00, 0x80, 0x32,
    0x08, 0x0B, 0x00, 0x02, 0x02, 0x02, 0x01, 0x00,
    0x09, 0x04, 0x00, 0x00, 0x01, 0x02, 0x02, 0x01, 0x00,
    0x05, 0x24, 0x00, 0x10, 0x01,
    0x05, 0x24, 0x01, 0x00, 0x00,
    0x04, 0x24, 0x02, 0x02,
    0x05, 0x24, 0x06, 0x00, 0x01,
    0x07, 0x05, 0x82, 0x03, 0x08, 0x00, 0x10,
    0x09, 0x04, 0x01, 0x00, 0x02, 0x0A, 0x00, 0x00, 0x00,
    0x07, 0x05, 0x03, 0x02, 0x40, 0x00, 0x00,
    0x07, 0x05, 0x84, 0x02, 0x40, 0x00, 0x00,
};

// ============================================================================
// TinyUSB Callbacks
// ============================================================================
void tud_mount_cb(void) {
    s_ctx.connected = true;
    ESP_LOGI(TAG, "USB mounted");
}

void tud_umount_cb(void) {
    s_ctx.connected = false;
    ESP_LOGI(TAG, "USB unmounted");
}

void tud_suspend_cb(bool remote_wakeup_en) {
    (void)remote_wakeup_en;
    ESP_LOGI(TAG, "USB suspended");
}

void tud_resume_cb(void) {
    ESP_LOGI(TAG, "USB resumed");
}

void tud_cdc_line_state_cb(uint8_t itf, bool dtr, bool rts) {
    (void)itf; (void)dtr; (void)rts;
}

void tud_cdc_line_coding_cb(uint8_t itf, cdc_line_coding_t const *p_line_coding) {
    (void)itf; (void)p_line_coding;
}

void tud_cdc_rx_cb(uint8_t itf) {
    (void)itf;
}

// ============================================================================
// Internal Helpers
// ============================================================================
static void send_error(ps_error_e err) {
    if (s_ctx.on_error_cb) {
        s_ctx.on_error_cb(err, s_ctx.user_ctx);
    }
}

static ps_error_e send_frame_internal(uint8_t type, const void *payload, uint16_t len) {
    if (!s_ctx.connected) return PS_ERR_USB;

    uint8_t frame[PS_MAX_FRAME_SIZE];
    size_t frame_len = 0;
    ps_error_e err = ps_encode_frame(type, payload, len, frame, &frame_len);
    if (err != PS_OK) return err;

    size_t written = ringbuf_write(&s_ctx.tx_ring, frame, frame_len);
    if (written != frame_len) {
        return PS_ERR_USB;
    }

    return PS_OK;
}

static void process_rx(void) {
    uint8_t temp[256];
    uint32_t count = tud_cdc_n_available(0);
    if (count == 0) return;
    if (count > sizeof(temp)) count = sizeof(temp);

    uint32_t read = tud_cdc_read(0, temp, count);
    if (read == 0) return;

    if (s_ctx.rx_len + read > USB_CDC_RX_BUF_SIZE) {
        s_ctx.rx_len = 0;
    }
    memcpy(s_ctx.rx_buf + s_ctx.rx_len, temp, read);
    s_ctx.rx_len += read;

    size_t consumed = 0;
    while (s_ctx.rx_len - consumed >= PS_FRAME_OVERHEAD) {
        size_t sof_pos = 0;
        while (sof_pos < s_ctx.rx_len && s_ctx.rx_buf[sof_pos] != PS_SOF) {
            sof_pos++;
        }
        if (sof_pos > 0) {
            consumed += sof_pos;
            if (sof_pos > 0) {
                memmove(s_ctx.rx_buf, s_ctx.rx_buf + sof_pos, s_ctx.rx_len - consumed);
                s_ctx.rx_len -= consumed;
                consumed = 0;
            }
        }

        if (s_ctx.rx_len < PS_FRAME_OVERHEAD) break;

        uint16_t payload_len = s_ctx.rx_buf[2] | (s_ctx.rx_buf[3] << 8);
        size_t frame_len = payload_len + PS_FRAME_OVERHEAD;

        if (s_ctx.rx_len < frame_len) break;

        uint8_t type;
        const uint8_t *payload;
        uint16_t p_len;
        ps_error_e err = ps_decode_frame(s_ctx.rx_buf, frame_len, &type, &payload, &p_len);
        if (err == PS_OK) {
            if (s_ctx.on_frame_cb) {
                s_ctx.on_frame_cb(type, payload, p_len, s_ctx.user_ctx);
            }
        } else if (err == PS_ERR_CRC) {
            send_error(PS_ERR_CRC);
        }

        consumed += frame_len;
    }

    if (consumed > 0) {
        if (consumed < s_ctx.rx_len) {
            memmove(s_ctx.rx_buf, s_ctx.rx_buf + consumed, s_ctx.rx_len - consumed);
        }
        s_ctx.rx_len -= consumed;
    }
}

static void flush_tx(void) {
    if (!s_ctx.connected) return;

    uint8_t buf[256];
    while (true) {
        size_t avail = ringbuf_read_space(&s_ctx.tx_ring);
        if (avail == 0) break;

        size_t read = ringbuf_read(&s_ctx.tx_ring, buf, sizeof(buf));
        if (read == 0) break;

        tud_cdc_write(0, buf, read);
        tud_cdc_write_flush(0);
    }
}

// ============================================================================
// Public API
// ============================================================================
ps_error_e usb_cdc_init(void) {
    tusb_init();

    ringbuf_init(&s_ctx.tx_ring, s_ctx.tx_ring_buf, USB_CDC_TX_BUF_SIZE);

    s_ctx.tx_mutex = xSemaphoreCreateMutex();
    if (!s_ctx.tx_mutex) return PS_ERR_MEMORY;

    int retries = 100;
    while (retries-- > 0 && !s_ctx.tinyusb_started) {
        vTaskDelay(pdMS_TO_TICKS(10));
    }

    ESP_LOGI(TAG, "USB CDC initialized");
    return PS_OK;
}

void usb_cdc_set_callbacks(usb_on_frame_t on_frame, usb_on_error_t on_error, void *ctx) {
    s_ctx.on_frame_cb = on_frame;
    s_ctx.on_error_cb = on_error;
    s_ctx.user_ctx = ctx;
}

ps_error_e usb_cdc_send_frame(uint8_t type, const void *payload, uint16_t len) {
    if (xSemaphoreTake(s_ctx.tx_mutex, pdMS_TO_TICKS(100)) != pdTRUE) {
        return PS_ERR_TIMEOUT;
    }
    ps_error_e err = send_frame_internal(type, payload, len);
    xSemaphoreGive(s_ctx.tx_mutex);
    return err;
}

ps_error_e usb_cdc_send_ack(uint8_t cmd_type, ps_error_e status) {
    ps_ack_t ack = {.cmd_type = cmd_type, .status = (uint8_t)status};
    return usb_cdc_send_frame(PS_ACK, &ack, sizeof(ack));
}

ps_error_e usb_cdc_send_data_chunk(uint16_t sequence, uint32_t timestamp_us,
                                    uint32_t sample_count, const uint8_t *samples, uint16_t flags) {
    if (!s_ctx.connected) return PS_ERR_USB;

    ps_evt_data_chunk_t hdr = {
        .sequence = sequence,
        .flags = flags,
        .timestamp_us = timestamp_us,
        .sample_count = sample_count,
    };

    size_t frame_len = sizeof(hdr) + sample_count + PS_FRAME_OVERHEAD;
    if (ringbuf_write_space(&s_ctx.tx_ring) < frame_len) {
        return PS_ERR_OVERRUN;
    }

    uint8_t frame[PS_MAX_FRAME_SIZE];
    size_t written = 0;

    frame[written++] = PS_SOF;
    frame[written++] = PS_EVT_DATA_CHUNK;
    frame[written++] = 0;
    frame[written++] = 0;
    memcpy(frame + written, &hdr, sizeof(hdr));
    written += sizeof(hdr);
    memcpy(frame + written, samples, sample_count);
    written += sample_count;

    uint16_t payload_len = sizeof(hdr) + sample_count;
    frame[2] = payload_len & 0xFF;
    frame[3] = (payload_len >> 8) & 0xFF;

    uint32_t crc = ps_crc32(frame, written);
    frame[written++] = crc & 0xFF;
    frame[written++] = (crc >> 8) & 0xFF;
    frame[written++] = (crc >> 16) & 0xFF;
    frame[written++] = (crc >> 24) & 0xFF;

    frame[written++] = PS_EOF;

    size_t r = ringbuf_write(&s_ctx.tx_ring, frame, written);
    if (r != written) {
        return PS_ERR_USB;
    }

    return PS_OK;
}

ps_error_e usb_cdc_send_trigger_hit(uint32_t sample_index, uint32_t timestamp_us, uint8_t source) {
    ps_evt_trigger_hit_t evt = {
        .sample_index = sample_index,
        .timestamp_us = timestamp_us,
        .trigger_source = source,
    };
    return usb_cdc_send_frame(PS_EVT_TRIGGER_HIT, &evt, sizeof(evt));
}

ps_error_e usb_cdc_send_capture_done(uint32_t total_samples, uint32_t duration_us,
                                      uint16_t chunks_sent, uint8_t status) {
    ps_evt_capture_done_t evt = {
        .total_samples = total_samples,
        .duration_us = duration_us,
        .chunks_sent = chunks_sent,
        .status = status,
    };
    return usb_cdc_send_frame(PS_EVT_CAPTURE_DONE, &evt, sizeof(evt));
}

ps_error_e usb_cdc_send_error(ps_error_e code, const char *message) {
    ps_evt_error_t evt = {
        .error_code = (uint8_t)code,
    };
    return usb_cdc_send_frame(PS_EVT_ERROR, &evt, sizeof(evt));
}

void usb_cdc_task(void *arg) {
    (void)arg;
    ESP_LOGI(TAG, "USB CDC task started");

    while (1) {
        if (s_ctx.connected) {
            process_rx();
            flush_tx();
        }
        vTaskDelay(pdMS_TO_TICKS(1));
    }
}

bool usb_cdc_is_connected(void) {
    return s_ctx.connected && tud_cdc_connected();
}

size_t usb_cdc_get_tx_depth(void) {
    return ringbuf_read_space(&s_ctx.tx_ring);
}

ps_error_e usb_cdc_flush(uint32_t timeout_ms) {
    uint32_t start = xTaskGetTickCount();
    while (ringbuf_read_space(&s_ctx.tx_ring) > 0) {
        if (xTaskGetTickCount() - start > pdMS_TO_TICKS(timeout_ms)) {
            return PS_ERR_TIMEOUT;
        }
        vTaskDelay(pdMS_TO_TICKS(1));
    }
    return PS_OK;
}