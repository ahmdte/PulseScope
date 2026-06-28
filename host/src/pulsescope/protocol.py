"""
PulseScope protocol codec for host-side frame encoding/decoding.

Frame format (little-endian):
| SOF(1) | TYPE(1) | LEN(2) | PAYLOAD(N) | CRC32(4) | EOF(1) |

Copyright (c) 2024 PulseScope Contributors
SPDX-License-Identifier: MIT
"""
import struct
import binascii
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Tuple, Iterator
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================
SOF = 0xAA
EOF = 0x55
FRAME_OVERHEAD = 8
MAX_PAYLOAD = 1024
PROTOCOL_VERSION = 1

class FrameType(IntEnum):
    CMD_START       = 0x01
    CMD_STOP        = 0x02
    CMD_CONFIG      = 0x03
    CMD_GET_INFO    = 0x04
    CMD_SELF_TEST   = 0x05
    CMD_PING        = 0x06
    EVT_DATA_CHUNK  = 0x10
    EVT_TRIGGER_HIT = 0x11
    EVT_CAPTURE_DONE= 0x12
    EVT_ERROR       = 0x13
    EVT_INFO        = 0x14
    EVT_PONG        = 0x15
    ACK             = 0xF0
    NACK            = 0xF1

class TriggerMode(IntEnum):
    NONE       = 0
    EDGE       = 1
    PULSE      = 2
    PATTERN    = 3
    UART_START = 4
    SPI_CS     = 5

class TriggerEdge(IntEnum):
    RISING  = 0
    FALLING = 1
    EITHER  = 2

class ErrorCode(IntEnum):
    OK              = 0
    INVALID_ARG     = 1
    BUSY            = 2
    OVERRUN         = 3
    USB             = 4
    TRIGGER         = 5
    RATE            = 6
    MEMORY          = 7
    TIMEOUT         = 8
    CRC             = 9
    PROTOCOL        = 10

CRC32_TABLE = None

def _build_crc32_table():
    global CRC32_TABLE
    if CRC32_TABLE is not None:
        return
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xEDB88320
            else:
                crc >>= 1
        table.append(crc)
    CRC32_TABLE = tuple(table)

def crc32(data: bytes) -> int:
    _build_crc32_table()
    crc = 0xFFFFFFFF
    for b in data:
        crc = (crc >> 8) ^ CRC32_TABLE[(crc ^ b) & 0xFF]
    return ~crc & 0xFFFFFFFF

@dataclass
class Frame:
    type: FrameType
    payload: bytes
    sequence: int = 0

    def encode(self) -> bytes:
        payload_len = len(self.payload)
        if payload_len > MAX_PAYLOAD:
            raise ValueError(f"Payload too large: {payload_len} > {MAX_PAYLOAD}")

        header = struct.pack('<BBH', SOF, self.type, payload_len)
        frame = header + self.payload
        crc = crc32(frame)
        frame += struct.pack('<I', crc)
        frame += struct.pack('<B', EOF)
        return frame

    @classmethod
    def decode(cls, data: bytes) -> 'Frame':
        if len(data) < FRAME_OVERHEAD:
            raise ValueError("Frame too short")
        if data[0] != SOF or data[-1] != EOF:
            raise ValueError("Invalid SOF/EOF")

        frame_type, payload_len = struct.unpack('<BH', data[1:4])
        if payload_len > MAX_PAYLOAD:
            raise ValueError(f"Invalid payload length: {payload_len}")

        expected_len = FRAME_OVERHEAD + payload_len
        if len(data) != expected_len:
            raise ValueError(f"Frame length mismatch: {len(data)} != {expected_len}")

        payload = data[4:4+payload_len]
        received_crc = struct.unpack('<I', data[4+payload_len:8+payload_len])[0]
        computed_crc = crc32(data[:4+payload_len])
        if received_crc != computed_crc:
            raise ValueError(f"CRC mismatch: expected {computed_crc:08X}, got {received_crc:08X}")

        return cls(type=FrameType(frame_type), payload=payload)

    def __bytes__(self) -> bytes:
        return self.encode()

@dataclass
class CmdStart:
    sample_rate_hz: int
    num_samples: int
    trigger_mode: TriggerMode = TriggerMode.EDGE
    trigger_channel: int = 0
    trigger_edge: TriggerEdge = TriggerEdge.RISING
    trigger_pattern: int = 0
    trigger_pulse_min_ns: int = 0
    trigger_pulse_max_ns: int = 0
    pretrigger_samples: int = 0

    def encode(self) -> bytes:
        return struct.pack('<IIBBBIII',
            self.sample_rate_hz,
            self.num_samples,
            self.trigger_mode,
            self.trigger_channel,
            self.trigger_edge,
            self.trigger_pattern,
            self.trigger_pulse_min_ns,
            self.trigger_pulse_max_ns,
            self.pretrigger_samples,
        )

@dataclass
class EvtInfo:
    protocol_version: int = 1
    hw_version: Tuple[int, int, int] = (1, 0, 0)
    fw_version: int = 0x010000
    max_sample_rate_hz: int = 20_000_000
    max_samples: int = 524_288
    num_channels: int = 4
    capabilities: int = 0xFF
    device_name: str = "PulseScope"

    @classmethod
    def decode(cls, payload: bytes) -> 'EvtInfo':
        if len(payload) < 40:
            raise ValueError("Info payload too short")
        vals = struct.unpack('<BBBIIIBBBII', payload[:40])
        name = payload[40:].decode('ascii').rstrip('\x00')
        return cls(
            protocol_version=vals[0],
            hw_version=(vals[1], vals[2], vals[3]),
            fw_version=vals[4],
            max_sample_rate_hz=vals[5],
            max_samples=vals[6],
            num_channels=vals[7],
            capabilities=vals[9],
            device_name=name,
        )

@dataclass
class EvtDataChunk:
    sequence: int
    flags: int
    timestamp_us: int
    sample_count: int
    samples: bytes

    @classmethod
    def decode(cls, payload: bytes) -> 'EvtDataChunk':
        if len(payload) < 12:
            raise ValueError("Data chunk payload too short")
        seq, flags, ts, count = struct.unpack('<HHI I', payload[:12])
        samples = payload[12:]
        expected = count * 1
        if len(samples) != expected:
            logger.warning(f"Sample count mismatch: expected {expected}, got {len(samples)}")
        return cls(sequence=seq, flags=flags, timestamp_us=ts, sample_count=count, samples=samples)

@dataclass
class EvtTriggerHit:
    sample_index: int
    timestamp_us: int
    trigger_source: int

    @classmethod
    def decode(cls, payload: bytes) -> 'EvtTriggerHit':
        idx, ts, src = struct.unpack('<IIB', payload[:9])
        return cls(sample_index=idx, timestamp_us=ts, trigger_source=src)

@dataclass
class EvtCaptureDone:
    total_samples: int
    duration_us: int
    chunks_sent: int
    status: int

    @classmethod
    def decode(cls, payload: bytes) -> 'EvtCaptureDone':
        total, dur, chunks, status = struct.unpack('<IIHB', payload[:13])
        return cls(total_samples=total, duration_us=dur, chunks_sent=chunks, status=status)

@dataclass
class Ack:
    cmd_type: int
    status: ErrorCode

    @classmethod
    def decode(cls, payload: bytes) -> 'Ack':
        cmd, status = struct.unpack('<BB', payload[:2])
        return cls(cmd_type=cmd, status=ErrorCode(status))

class FrameStreamDecoder:
    def __init__(self):
        self.buffer = bytearray()
        self.max_buffer = 16384

    def feed(self, data: bytes) -> Iterator[Frame]:
        self.buffer.extend(data)
        if len(self.buffer) > self.max_buffer:
            sof = self.buffer.find(SOF, 1)
            if sof > 0:
                self.buffer = self.buffer[sof:]
            else:
                self.buffer.clear()

        while True:
            try:
                sof_idx = self.buffer.index(SOF)
            except ValueError:
                self.buffer.clear()
                break

            if sof_idx > 0:
                self.buffer = self.buffer[sof_idx:]

            if len(self.buffer) < 4:
                break

            payload_len = struct.unpack('<H', self.buffer[2:4])[0]
            frame_len = FRAME_OVERHEAD + payload_len

            if len(self.buffer) < frame_len:
                break

            frame_data = bytes(self.buffer[:frame_len])
            try:
                frame = Frame.decode(frame_data)
                yield frame
            except ValueError as e:
                logger.warning(f"Frame decode error: {e}")
                next_sof = self.buffer.find(SOF, 1)
                if next_sof > 0:
                    self.buffer = self.buffer[next_sof:]
                    continue
                else:
                    self.buffer.clear()
                    break

            self.buffer = self.buffer[frame_len:]

def make_start_frame(cmd: CmdStart) -> Frame:
    return Frame(FrameType.CMD_START, cmd.encode())

def make_stop_frame() -> Frame:
    return Frame(FrameType.CMD_STOP, b'')

def make_get_info_frame() -> Frame:
    return Frame(FrameType.CMD_GET_INFO, b'')

def make_ping_frame() -> Frame:
    return Frame(FrameType.CMD_PING, b'')

def make_self_test_frame() -> Frame:
    return Frame(FrameType.CMD_SELF_TEST, b'')

def parse_frame(data: bytes) -> Frame:
    return Frame.decode(data)