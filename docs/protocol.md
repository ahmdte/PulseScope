# PulseScope Wire Protocol Specification

Version: 1.0  
Last Updated: 2024

---

## Overview

PulseScope uses a framed binary protocol over USB CDC-ACM for all host↔device communication. The protocol provides:

- **Framing**: Every message is framed with SOF/EOF markers and length
- **Integrity**: CRC32 (IEEE 802.3) on every frame
- **Acknowledgment**: ACK/NACK for all commands
- **Streaming**: High-throughput data chunks with sequence numbers
- **Extensibility**: Versioned frames, reserved fields for future use

---

## Transport

- **Interface**: USB CDC-ACM (virtual COM port)
- **Baud Rate**: Ignored (USB bulk endpoints); logical rate ~2 Mbps
- **Flow Control**: None (host must pace commands; data chunks flow continuously during capture)

---

## Frame Format

All multi-byte fields are **little-endian**.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PULSESCOPE FRAME                                   │
├─────┬─────┬──────────┬──────────────────┬──────────┬─────┐                  │
│ SOF │TYPE │ LEN (2)  │  PAYLOAD (N)     │ CRC32(4) │ EOF │                  │
│ 0xAA│ 1B  │ (LE)     │    0-1024 bytes  │  (LE)    │0x55 │                  │
└─────┴─────┴──────────┴──────────────────┴──────────┴─────┘                  │
```

| Field | Size | Description |
|-------|------|-------------|
| SOF | 1 byte | Start of Frame marker: **0xAA** |
| TYPE | 1 byte | Frame type (see Frame Types below) |
| LEN | 2 bytes | Payload length (0-1024), little-endian |
| PAYLOAD | N bytes | Frame-specific payload |
| CRC32 | 4 bytes | CRC32 of all bytes from SOF through PAYLOAD, little-endian |
| EOF | 1 byte | End of Frame marker: **0x55** |

**Minimum frame size**: 8 bytes (empty payload)  
**Maximum frame size**: 1032 bytes (1024 payload + 8 overhead)

---

## Frame Types

### Host → Device (Commands: 0x00-0x7F)

| Type | Name | Payload | Response |
|------|------|---------|----------|
| 0x01 | `CMD_START` | `ps_cmd_start_t` | ACK |
| 0x02 | `CMD_STOP` | none | ACK |
| 0x03 | `CMD_CONFIG` | `ps_cmd_config_t` | ACK |
| 0x04 | `CMD_GET_INFO` | none | `EVT_INFO` |
| 0x05 | `CMD_SELF_TEST` | none | ACK |
| 0x06 | `CMD_PING` | none | `EVT_PONG` |

### Device → Host (Events: 0x10-0x7F)

| Type | Name | Payload | Description |
|------|------|---------|-------------|
| 0x10 | `EVT_DATA_CHUNK` | `ps_evt_data_chunk_t` | Samples chunk |
| 0x11 | `EVT_TRIGGER_HIT` | `ps_evt_trigger_hit_t` | Trigger fired |
| 0x12 | `EVT_CAPTURE_DONE` | `ps_evt_capture_done_t` | Capture complete |
| 0x13 | `EVT_ERROR` | `ps_evt_error_t` | Async error |
| 0x14 | `EVT_INFO` | `ps_evt_info_t` | Device info |
| 0x15 | `EVT_PONG` | none | Ping response |

### Acknowledgment (0xF0-0xFF)

| Type | Name | Payload | Description |
|------|------|---------|-------------|
| 0xF0 | `ACK` | `ps_ack_t` | Command OK |
| 0xF1 | `NACK` | `ps_ack_t` | Command failed (status = error code) |

---

## Payload Structures

### `CMD_START` Payload (28 bytes)

```c
typedef struct __attribute__((packed)) {
    uint32_t sample_rate_hz;      // Target sample rate in Hz (1000 - 20,000,000)
    uint32_t num_samples;         // Total samples to capture (0 = continuous)
    uint8_t  trigger_mode;        // ps_trigger_mode_e
    uint8_t  trigger_channel;     // 0-3
    uint8_t  trigger_edge;        // ps_trigger_edge_e
    uint8_t  reserved;
    uint32_t trigger_pattern;     // Pattern trigger: bits 0-3=mask, bits 4-7=value
    uint32_t trigger_pulse_min_ns; // Pulse trigger: minimum pulse width (ns)
    uint32_t trigger_pulse_max_ns; // Pulse trigger: maximum pulse width (ns)
    uint32_t pretrigger_samples;  // Samples to keep before trigger
} ps_cmd_start_t;
```

### `EVT_DATA_CHUNK` Payload (variable)

```c
typedef struct __attribute__((packed)) {
    uint16_t sequence;            // Incrementing sequence number (wraps at 65535)
    uint16_t flags;               // Bit 0: last chunk, Bit 1: trigger in chunk
    uint32_t timestamp_us;        // Microseconds since capture start
    uint32_t sample_count;        // Number of 4-channel samples in this chunk
    // uint8_t samples[sample_count] follows...
    // Each sample byte: bits 0-3 = CH0-CH3 (1 bit per channel)
} ps_evt_data_chunk_t;
```

**Sample Packing**: Each byte contains 4 channel samples:
```
Bit:    7 6 5 4 | 3 2 1 0
        --------+--------
        Ch3 Ch2 | Ch1 Ch0
```

### `EVT_TRIGGER_HIT` Payload (12 bytes)

```c
typedef struct __attribute__((packed)) {
    uint32_t sample_index;        // Absolute sample index where trigger fired
    uint32_t timestamp_us;        // Timestamp at trigger
    uint8_t  trigger_source;      // Channel or pattern value that triggered
    uint8_t  reserved[3];
} ps_evt_trigger_hit_t;
```

### `EVT_CAPTURE_DONE` Payload (14 bytes)

```c
typedef struct __attribute__((packed)) {
    uint32_t total_samples;       // Total samples captured
    uint32_t duration_us;         // Capture duration in microseconds
    uint16_t chunks_sent;         // Number of data chunks sent
    uint8_t  status;              // 0=success, 1=overrun, 2=USB error
    uint8_t  reserved;
} ps_evt_capture_done_t;
```

### `EVT_INFO` Payload (40+ bytes)

```c
typedef struct __attribute__((packed)) {
    uint8_t  protocol_version;    // Protocol version (1)
    uint8_t  hw_version_major;    // Hardware version
    uint8_t  hw_version_minor;
    uint8_t  hw_version_patch;
    uint32_t fw_version;          // 0xMMPPBB (major.minor.patch.build)
    uint32_t max_sample_rate_hz;  // Maximum supported sample rate
    uint32_t max_samples;         // Maximum samples per capture
    uint8_t  num_channels;        // Number of input channels (4)
    uint8_t  reserved[3];
    uint32_t capabilities;        // Bitfield (see Capabilities below)
    char     device_name[16];     // Null-terminated device name
} ps_evt_info_t;
```

### `ACK` / `NACK` Payload (4 bytes)

```c
typedef struct __attribute__((packed)) {
    uint8_t  cmd_type;            // Original command type
    uint8_t  status;              // 0=OK, >0=ErrorCode
    uint16_t reserved;
} ps_ack_t;
```

---

## Trigger Modes

### `ps_trigger_mode_e` (values)

| Value | Name | Description |
|-------|------|-------------|
| 0 | `NONE` | No trigger (free-running) |
| 1 | `EDGE` | Edge trigger on single channel |
| 2 | `PULSE` | Pulse width trigger |
| 3 | `PATTERN` | 4-bit pattern match |
| 4 | `UART_START` | UART start bit detection |
| 5 | `SPI_CS` | SPI chip select falling edge |

### `ps_trigger_edge_e` (values)

| Value | Name | Description |
|-------|------|-------------|
| 0 | `RISING` | Low → High |
| 1 | `FALLING` | High → Low |
| 2 | `EITHER` | Any transition |

### `ps_pulse_polarity_e` (values)

| Value | Name | Description |
|-------|------|-------------|
| 0 | `POSITIVE` | High pulse |
| 1 | `NEGATIVE` | Low pulse |
| 2 | `EITHER` | Any pulse |

---

## Error Codes

| Code | Name | Description |
|------|------|-------------|
| 0 | `OK` | Success |
| 1 | `INVALID_ARG` | Invalid parameter |
| 2 | `BUSY` | Device busy |
| 3 | `OVERRUN` | DMA/SRAM overrun |
| 4 | `USB` | USB communication error |
| 5 | `TRIGGER` | Trigger configuration error |
| 6 | `RATE` | Invalid sample rate |
| 7 | `MEMORY` | Out of memory |
| 8 | `TIMEOUT` | Operation timed out |
| 9 | `CRC` | Frame CRC mismatch |
| 10 | `PROTOCOL` | Framing/protocol error |

---

## Capabilities Bitfield

| Bit | Name | Description |
|-----|------|-------------|
| 0 | `TRIG_EDGE` | Edge trigger supported |
| 1 | `TRIG_PULSE` | Pulse width trigger |
| 2 | `TRIG_PATTERN` | Pattern trigger |
| 3 | `TRIG_UART` | UART start bit trigger |
| 4 | `TRIG_SPI` | SPI CS trigger |
| 5 | `TRIG_I2C` | I2C start condition trigger |
| 6 | `CONTINUOUS` | Continuous (non-stop) capture |
| 7 | `PRETRIGGER` | Pre-trigger samples supported |
| 8 | `VOLTAGE_5V` | 5V tolerant inputs |

---

## CRC32 Algorithm

- **Polynomial**: 0x04C11DB7 (IEEE 802.3 / Ethernet)
- **Initial value**: 0xFFFFFFFF
- **Final XOR**: 0xFFFFFFFF
- **Reflect input**: Yes
- **Reflect output**: Yes
- **Test vector**: CRC32("123456789") = 0xCBF43926

Example implementation (C):
```c
uint32_t crc32(const uint8_t *data, size_t len) {
    static const uint32_t table[256] = { ... }; // Precomputed
    uint32_t crc = 0xFFFFFFFF;
    for (size_t i = 0; i < len; i++) {
        crc = (crc >> 8) ^ table[(crc ^ data[i]) & 0xFF];
    }
    return ~crc;
}
```

---

## State Machine

### Host Perspective

```
IDLE
  │
  ├─► CMD_PING ──────► EVT_PONG ──────► IDLE
  │
  ├─► CMD_GET_INFO ──► EVT_INFO ──────► IDLE
  │
  ├─► CMD_SELF_TEST ─► ACK/NACK ──────► IDLE
  │
  ├─► CMD_CONFIG ────► ACK/NACK ──────► IDLE
  │
  └─► CMD_START ─────► ACK
                        │
                        ▼ (capture running)
              ┌───────────────────────┐
              │   Streaming State     │
              │  (receives data)      │
              └───────────────────────┘
                        │
                        ▼
              ┌───────────────────────┐
              │   EVT_TRIGGER_HIT     │ (optional)
              └───────────────────────┘
                        │
                        ▼
              ┌───────────────────────┐
              │   EVT_CAPTURE_DONE    │
              └───────────────────────┘
                        │
                        ▼
                         IDLE
```

### Device Perspective

```
IDLE
  │
  ├─► CMD_PING ──► EVT_PONG
  ├─► CMD_GET_INFO ──► EVT_INFO
  ├─► CMD_SELF_TEST ──► run test ──► ACK/NACK
  ├─► CMD_CONFIG ──► validate ──► ACK/NACK
  │
  └─► CMD_START ──► ARM
                    │
                    ▼ (DMA running, trigger evaluation)
           ┌─────────────────────┐
           │  CAPTURE_RUNNING    │
           ├─────────────────────┤
           │  - Fill DMA buffers │
           │  - Evaluate trigger │
           │  - Send data chunks │
           │  - If trigger:      │
           │      EVT_TRIGGER_HIT│
           │  - If done:         │
           │      EVT_CAPTURE_DONE
           └─────────────────────┘
                    │
                    ▼
                  IDLE
```

---

## Timing Constraints

| Operation | Max Latency |
|-----------|-------------|
| ACK/NACK response | < 10 ms |
| `EVT_INFO` response | < 50 ms |
| `EVT_PONG` response | < 5 ms |
| Data chunk interval | ~1-10 ms (depends on rate/chunk size) |
| Trigger hit notification | < 1 ms after trigger |

---

## Example Conversation

### Get Device Info
```
Host → Device:
AA 04 00 00   CRC32   55

Device → Host:
AA 14 28 00   [40-byte info payload]   CRC32   55
```

### Start Capture (10 MS/s, 100k samples, rising edge CH0)
```
Host → Device:
AA 01 1C 00   00 00 00 00  64 00 00 00  01 00 00 00  00 00 00 00
              00 00 00 00  00 00 00 00  00 00 00 00  CRC32   55
              │       │       │       │       │       │       │
              │       │       │       │       │       │       └─ pretrigger=0
              │       │       │       │       │       └─ pulse_max=0
              │       │       │       │       └─ pulse_min=0
              │       │       │       └─ pattern=0
              │       │       └─ edge=0 (RISING)
              │       └─ channel=0
              │       └─ mode=1 (EDGE)
              └─ samples=100000
              └─ sample_rate=0x00989680 = 10,000,000

Device → Host:
AA F0 04 00   01 00 00 00   CRC32   55   (ACK for CMD_START)
```

### Data Chunk (first chunk)
```
Device → Host:
AA 10 30 00   00 00   00 00   E8 03 00 00
              00 00 00 00   [48 bytes samples]   CRC32   55
              │    │    │    │    │       │
              │    │    │    │    │       └─ samples (48 bytes = 48 4-ch samples)
              │    │    │    │    └─ sample_count=1000 (0x000003E8)
              │    │    │    └─ timestamp=1000us
              │    │    └─ flags=0
              │    └─ sequence=0
```

### Capture Done
```
Device → Host:
AA 12 0E 00   64 00 00 00  E8 03 00 00  04 00  00 00   CRC32   55
              │       │       │       │    │    │
              │       │       │       │    │    └─ status=0
              │       │       │       │    └─ chunks_sent=4
              │       │       │       └─ duration_us=100000 (0.1s)
              │       │       └─ total_samples=100000
```

---

## Implementation Notes

### Host Responsibilities
1. **Pace commands** — Wait for ACK before sending next command
2. **Handle data chunks** — Process in sequence order; handle sequence wrap
3. **Validate CRC** — Drop corrupted frames, log errors
4. **Timeout handling** — Respect max latencies above

### Device Responsibilities
1. **ACK every command** — Even invalid ones (respond with NACK)
2. **Stream data chunks** — Keep USB TX buffer full; don't stall
3. **Trigger hit timing** — Send `EVT_TRIGGER_HIT` within 1ms
4. **Graceful stop** — Finish current DMA buffer, send `EVT_CAPTURE_DONE`

### Error Recovery
- **CRC error on RX**: Host sends `CMD_STOP`, restarts capture
- **Sequence gap**: Host logs gap, attempts to resync on next chunk
- **USB stall**: Host resets USB interface, reconnects
- **Device error**: Host reads `EVT_ERROR`, logs, restarts session

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2024 | Initial release |

---

## References

- [ESP-IDF I2S Parallel Mode](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/peripherals/i2s.html)
- [TinyUSB CDC-ACM](https://github.com/tinyusb/tinyusb)
- [CRC32 IEEE 802.3](https://en.wikipedia.org/wiki/Cyclic_redundancy_check#CRC-32_algorithm)