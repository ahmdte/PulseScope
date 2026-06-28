/**
 * @file protocol.h
 * @brief Wire protocol definitions for PulseScope host↔device communication
 *
 * All multi-byte fields are LITTLE ENDIAN.
 * Frame format: | SOF(1) | TYPE(1) | LEN(2) | PAYLOAD(N) | CRC32(4) | EOF(1) |
 */
#pragma once

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

// ============================================================================
// Frame Constants
// ============================================================================
#define PS_SOF                  0xAA
#define PS_EOF                  0x55
#define PS_FRAME_OVERHEAD       8   // SOF + TYPE + LEN(2) + CRC32(4) + EOF
#define PS_MAX_PAYLOAD          1024
#define PS_MAX_FRAME_SIZE       (PS_MAX_PAYLOAD + PS_FRAME_OVERHEAD)
#define PS_PROTOCOL_VERSION     1

// ============================================================================
// Frame Types (Host -> Device: 0x00-0x7F, Device -> Host: 0x80-0xFF)
// ============================================================================
typedef enum {
    // Host -> Device commands
    PS_CMD_START        = 0x01,
    PS_CMD_STOP         = 0x02,
    PS_CMD_CONFIG       = 0x03,
    PS_CMD_GET_INFO     = 0x04,
    PS_CMD_SELF_TEST    = 0x05,
    PS_CMD_PING         = 0x06,

    // Device -> Host responses/events
    PS_EVT_DATA_CHUNK   = 0x10,
    PS_EVT_TRIGGER_HIT  = 0x11,
    PS_EVT_CAPTURE_DONE = 0x12,
    PS_EVT_ERROR        = 0x13,
    PS_EVT_INFO         = 0x14,
    PS_EVT_PONG         = 0x15,

    // ACK/NACK
    PS_ACK              = 0xF0,
    PS_NACK             = 0xF1,
} ps_frame_type_e;

// ============================================================================
// Payload Structures
// ============================================================================

// CMD_START payload
typedef struct __attribute__((packed)) {
    uint32_t sample_rate_hz;      // Target sample rate (Hz)
    uint32_t num_samples;         // Total samples to capture (0 = continuous)
    uint8_t  trigger_mode;        // See ps_trigger_mode_e
    uint8_t  trigger_channel;     // 0-3
    uint8_t  trigger_edge;        // See ps_trigger_edge_e
    uint8_t  reserved;
    uint32_t trigger_pattern;     // For pattern trigger (mask in lower 4 bits, value in upper 4)
    uint32_t trigger_pulse_min_ns; // For pulse-width trigger
    uint32_t trigger_pulse_max_ns;
    uint32_t pretrigger_samples;  // Samples before trigger
} ps_cmd_start_t;

// CMD_CONFIG payload
typedef struct __attribute__((packed)) {
    uint8_t  gpio_map[4];         // GPIO numbers for CH0-3
    uint8_t  active_channels;     // Bitmask of active channels
    uint16_t reserved;
    uint32_t sample_rate_hz;      // Actual sample rate (device reports)
    uint32_t max_samples;         // Max samples per capture (RAM limit)
} ps_cmd_config_t;

// EVT_DATA_CHUNK payload (variable length)
typedef struct __attribute__((packed)) {
    uint16_t sequence;            // Incrementing sequence number
    uint16_t flags;               // Bit 0: last chunk, Bit 1: trigger in this chunk
    uint32_t timestamp_us;        // Microseconds since capture start
    uint32_t sample_count;        // Number of 4-channel samples in this chunk
    // uint8_t data[sample_count * 4] follows (packed: 4 bits per sample, or 1 byte per channel)
} ps_evt_data_chunk_t;

// EVT_TRIGGER_HIT payload
typedef struct __attribute__((packed)) {
    uint32_t sample_index;        // Absolute sample index where trigger occurred
    uint32_t timestamp_us;        // Timestamp at trigger
    uint8_t  trigger_source;      // Channel or pattern that triggered
    uint8_t  reserved[3];
} ps_evt_trigger_hit_t;

// EVT_CAPTURE_DONE payload
typedef struct __attribute__((packed)) {
    uint32_t total_samples;
    uint32_t duration_us;
    uint16_t chunks_sent;
    uint8_t  status;              // 0=success, 1=buffer overrun, 2=USB error
    uint8_t  reserved;
} ps_evt_capture_done_t;

// EVT_ERROR payload
typedef struct __attribute__((packed)) {
    uint8_t  error_code;
    uint8_t  reserved[3];
    // char message[] follows (null-terminated)
} ps_evt_error_t;

// ACK/NACK payload
typedef struct __attribute__((packed)) {
    uint8_t  cmd_type;            // Original command type
    uint8_t  status;              // 0=OK, non-zero=error code
    uint16_t reserved;
} ps_ack_t;

// EVT_INFO payload (response to CMD_GET_INFO)
typedef struct __attribute__((packed)) {
    uint8_t  protocol_version;
    uint8_t  hw_version_major;
    uint8_t  hw_version_minor;
    uint8_t  hw_version_patch;
    uint32_t fw_version;          // e.g. 0x010000 = v1.0.0
    uint32_t max_sample_rate_hz;
    uint32_t max_samples;
    uint8_t  num_channels;
    uint8_t  reserved[3];
    uint32_t capabilities;        // Bitfield: TRIG_EDGE=1, TRIG_PULSE=2, TRIG_PATTERN=4, TRIG_UART=8, etc.
    char     device_name[16];     // Null-terminated
} ps_evt_info_t;

// ============================================================================
// Trigger Enumerations
// ============================================================================
typedef enum {
    PS_TRIG_NONE       = 0,
    PS_TRIG_EDGE       = 1,
    PS_TRIG_PULSE      = 2,
    PS_TRIG_PATTERN    = 3,
    PS_TRIG_UART_START = 4,
    PS_TRIG_SPI_CS     = 5,
} ps_trigger_mode_e;

typedef enum {
    PS_TRIG_EDGE_RISING  = 0,
    PS_TRIG_EDGE_FALLING = 1,
    PS_TRIG_EDGE_EITHER  = 2,
} ps_trigger_edge_e;

typedef enum {
    PS_PULSE_POSITIVE = 0,
    PS_PULSE_NEGATIVE = 1,
    PS_PULSE_EITHER   = 2,
} ps_pulse_polarity_e;

// ============================================================================
// Error Codes
// ============================================================================
typedef enum {
    PS_OK              = 0,
    PS_ERR_INVALID_ARG = 1,
    PS_ERR_BUSY        = 2,
    PS_ERR_OVERRUN     = 3,
    PS_ERR_USB         = 4,
    PS_ERR_TRIGGER     = 5,
    PS_ERR_RATE        = 6,
    PS_ERR_MEMORY      = 7,
    PS_ERR_TIMEOUT     = 8,
    PS_ERR_CRC         = 9,
    PS_ERR_PROTOCOL    = 10,
} ps_error_e;

// ============================================================================
// Capability Bitfield
// ============================================================================
#define PS_CAP_TRIG_EDGE      (1u << 0)
#define PS_CAP_TRIG_PULSE     (1u << 1)
#define PS_CAP_TRIG_PATTERN   (1u << 2)
#define PS_CAP_TRIG_UART      (1u << 3)
#define PS_CAP_TRIG_SPI       (1u << 4)
#define PS_CAP_TRIG_I2C       (1u << 5)
#define PS_CAP_CONTINUOUS     (1u << 6)
#define PS_CAP_PRETRIGGER     (1u << 7)
#define PS_CAP_VOLTAGE_5V     (1u << 8)

#define PS_DEFAULT_CAPABILITIES (PS_CAP_TRIG_EDGE | PS_CAP_TRIG_PULSE | \
                                  PS_CAP_TRIG_PATTERN | PS_CAP_PRETRIGGER)

// ============================================================================
// Frame Encode/Decode API
// ============================================================================

/**
 * @brief Compute CRC32 (IEEE 802.3 polynomial 0x04C11DB7)
 */
uint32_t ps_crc32(const uint8_t *data, size_t len);

/**
 * @brief Encode a frame into buffer
 * @param type Frame type
 * @param payload Pointer to payload (can be NULL if len=0)
 * @param payload_len Length of payload
 * @param out_buf Output buffer (must be >= payload_len + PS_FRAME_OVERHEAD)
 * @param out_len [out] Actual frame size written
 * @return PS_OK on success
 */
ps_error_e ps_encode_frame(uint8_t type, const void *payload, uint16_t payload_len,
                           uint8_t *out_buf, size_t *out_len);

/**
 * @brief Decode a frame from buffer
 * @param buf Input buffer
 * @param len Length of buffer
 * @param out_type [out] Frame type
 * @param out_payload [out] Payload start (points into buf)
 * @param out_payload_len [out] Payload length
 * @return PS_OK on success, PS_ERR_CRC if checksum fails, PS_ERR_PROTOCOL if framing invalid
 */
ps_error_e ps_decode_frame(const uint8_t *buf, size_t len,
                           uint8_t *out_type,
                           const uint8_t **out_payload,
                           uint16_t *out_payload_len);

/**
 * @brief Validate frame structure (SOF/EOF/CRC) without full decode
 */
ps_error_e ps_validate_frame(const uint8_t *buf, size_t len);

#ifdef __cplusplus
}
#endif