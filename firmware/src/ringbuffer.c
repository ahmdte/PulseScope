/*
 * Copyright (c) 2024 PulseScope Contributors
 *
 * SPDX-License-Identifier: MIT
 */

/**
 * @file ringbuffer.c
 * @brief Lock-free SPSC ring buffer implementation
 */
#include "ringbuffer.h"
#include <string.h>

void ringbuf_init(ringbuf_t *rb, uint8_t *buf, size_t capacity) {
    rb->buffer = buf;
    rb->capacity = capacity;
    rb->mask = capacity - 1;
    atomic_init(&rb->head, 0);
    atomic_init(&rb->tail, 0);
    atomic_init(&rb->full, false);
}

size_t ringbuf_write(ringbuf_t *rb, const uint8_t *data, size_t len) {
    size_t space = ringbuf_write_space(rb);
    if (len > space) len = space;
    if (len == 0) return 0;

    size_t head = atomic_load_explicit(&rb->head, memory_order_relaxed);
    size_t tail = atomic_load_explicit(&rb->tail, memory_order_acquire);
    size_t to_end = rb->capacity - head;

    if (len <= to_end) {
        memcpy(rb->buffer + head, data, len);
    } else {
        memcpy(rb->buffer + head, data, to_end);
        memcpy(rb->buffer, data + to_end, len - to_end);
    }

    atomic_store_explicit(&rb->head, (head + len) & rb->mask, memory_order_release);

    if (len == space) {
        atomic_store_explicit(&rb->full, true, memory_order_release);
    }

    return len;
}

size_t ringbuf_read(ringbuf_t *rb, uint8_t *data, size_t len) {
    size_t space = ringbuf_read_space(rb);
    if (len > space) len = space;
    if (len == 0) return 0;

    size_t tail = atomic_load_explicit(&rb->tail, memory_order_relaxed);
    size_t head = atomic_load_explicit(&rb->head, memory_order_acquire);
    size_t to_end = rb->capacity - tail;

    if (len <= to_end) {
        memcpy(data, rb->buffer + tail, len);
    } else {
        memcpy(data, rb->buffer + tail, to_end);
        memcpy(data + to_end, rb->buffer, len - to_end);
    }

    atomic_store_explicit(&rb->tail, (tail + len) & rb->mask, memory_order_release);
    atomic_store_explicit(&rb->full, false, memory_order_release);

    return len;
}

ps_error_e ringbuf_write_blocking(ringbuf_t *rb, const uint8_t *data, size_t len, uint32_t timeout_ms) {
    uint32_t start = xTaskGetTickCount();
    size_t total = 0;

    while (total < len) {
        size_t wrote = ringbuf_write(rb, data + total, len - total);
        total += wrote;
        if (total >= len) break;

        if (xTaskGetTickCount() - start > pdMS_TO_TICKS(timeout_ms)) {
            return PS_ERR_TIMEOUT;
        }
        vTaskDelay(pdMS_TO_TICKS(1));
    }
    return PS_OK;
}

size_t ringbuf_peek(const ringbuf_t *rb, uint8_t *data, size_t len) {
    size_t space = ringbuf_read_space(rb);
    if (len > space) len = space;
    if (len == 0) return 0;

    size_t tail = atomic_load_explicit(&rb->tail, memory_order_acquire);
    size_t to_end = rb->capacity - tail;

    if (len <= to_end) {
        memcpy(data, rb->buffer + tail, len);
    } else {
        memcpy(data, rb->buffer + tail, to_end);
        memcpy(data + to_end, rb->buffer, len - to_end);
    }

    return len;
}

size_t ringbuf_consume(ringbuf_t *rb, size_t len) {
    size_t space = ringbuf_read_space(rb);
    if (len > space) len = space;
    if (len == 0) return 0;

    atomic_store_explicit(&rb->tail,
                         (atomic_load_explicit(&rb->tail, memory_order_relaxed) + len) & rb->mask,
                         memory_order_release);
    atomic_store_explicit(&rb->full, false, memory_order_release);

    return len;
}

void ringbuf_reset(ringbuf_t *rb) {
    atomic_store_explicit(&rb->head, 0, memory_order_relaxed);
    atomic_store_explicit(&rb->tail, 0, memory_order_relaxed);
    atomic_store_explicit(&rb->full, false, memory_order_relaxed);
}