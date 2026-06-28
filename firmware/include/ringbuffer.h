/*
 * Copyright (c) 2024 PulseScope Contributors
 *
 * SPDX-License-Identifier: MIT
 */

/**
 * @file ringbuffer.h
 * @brief Lock-free single-producer single-consumer ring buffer
 *
 * Optimized for DMA-to-USB transfer with minimal overhead.
 * Uses atomic operations for thread/task safety.
 */
#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <stdatomic.h>

#ifdef __cplusplus
extern "C" {
#endif

// ============================================================================
// Ring Buffer Structure
// ============================================================================
typedef struct {
    uint8_t *buffer;
    size_t   capacity;      // Power of 2
    size_t   mask;          // capacity - 1
    _Atomic size_t head;    // Write index (producer)
    _Atomic size_t tail;    // Read index (consumer)
    _Atomic bool   full;    // Full flag (distinguishes full from empty)
} ringbuf_t;

// ============================================================================
// Public API
// ============================================================================

/**
 * @brief Initialize ring buffer
 * @param rb Ring buffer struct
 * @param buf Pre-allocated buffer (must be power of 2 size)
 * @param capacity Buffer size in bytes
 */
void ringbuf_init(ringbuf_t *rb, uint8_t *buf, size_t capacity);

/**
 * @brief Get available write space
 */
static inline size_t ringbuf_write_space(const ringbuf_t *rb) {
    if (atomic_load(&rb->full)) return 0;
    size_t h = atomic_load_explicit(&rb->head, memory_order_relaxed);
    size_t t = atomic_load_explicit(&rb->tail, memory_order_acquire);
    return (t > h) ? (t - h - 1) : (rb->capacity - h + t - 1);
}

/**
 * @brief Get available read space
 */
static inline size_t ringbuf_read_space(const ringbuf_t *rb) {
    if (atomic_load(&rb->full)) return rb->capacity;
    size_t h = atomic_load_explicit(&rb->head, memory_order_relaxed);
    size_t t = atomic_load_explicit(&rb->tail, memory_order_acquire);
    return (h >= t) ? (h - t) : (rb->capacity - t + h);
}

/**
 * @brief Check if empty
 */
static inline bool ringbuf_is_empty(const ringbuf_t *rb) {
    return (atomic_load(&rb->head) == atomic_load(&rb->tail)) && !atomic_load(&rb->full);
}

/**
 * @brief Check if full
 */
static inline bool ringbuf_is_full(const ringbuf_t *rb) {
    return atomic_load(&rb->full);
}

/**
 * @brief Write data (non-blocking, returns bytes written)
 * @return Number of bytes actually written (may be < len if full)
 */
size_t ringbuf_write(ringbuf_t *rb, const uint8_t *data, size_t len);

/**
 * @brief Read data (non-blocking, returns bytes read)
 * @return Number of bytes actually read (may be < len if empty)
 */
size_t ringbuf_read(ringbuf_t *rb, uint8_t *data, size_t len);

/**
 * @brief Write exactly len bytes (blocking with timeout)
 * @return PS_OK if all written, PS_ERR_TIMEOUT if timeout
 */
ps_error_e ringbuf_write_blocking(ringbuf_t *rb, const uint8_t *data, size_t len, uint32_t timeout_ms);

/**
 * @brief Peek at data without consuming (returns bytes available)
 */
size_t ringbuf_peek(const ringbuf_t *rb, uint8_t *data, size_t len);

/**
 * @brief Advance read pointer (consume without copying)
 */
size_t ringbuf_consume(ringbuf_t *rb, size_t len);

/**
 * @brief Reset buffer (call only when no concurrent access)
 */
void ringbuf_reset(ringbuf_t *rb);

#ifdef __cplusplus
}
#endif