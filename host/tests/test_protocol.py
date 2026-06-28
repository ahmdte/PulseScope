"""
Tests for PulseScope protocol codec.

Copyright (c) 2024 PulseScope Contributors
SPDX-License-Identifier: MIT
"""
import pytest
from pulsescope.protocol import (
    Frame, FrameType, CmdStart, EvtInfo, EvtDataChunk, EvtTriggerHit,
    EvtCaptureDone, Ack, ErrorCode, TriggerMode, TriggerEdge,
    make_start_frame, make_stop_frame, make_get_info_frame, make_ping_frame,
    parse_frame, FrameStreamDecoder, crc32,
)


class TestCRC32:
    def test_crc32_empty(self):
        assert crc32(b'') == 0xFFFFFFFF

    def test_crc32_known(self):
        assert crc32(b'123456789') == 0xCBF43926

    def test_crc32_consistency(self):
        data = b'hello world'
        assert crc32(data) == crc32(data)


class TestFrameEncodeDecode:
    def test_simple_frame(self):
        frame = Frame(FrameType.CMD_PING, b'')
        encoded = frame.encode()
        decoded = Frame.decode(encoded)
        assert decoded.type == FrameType.CMD_PING
        assert decoded.payload == b''

    def test_frame_with_payload(self):
        payload = b'hello world'
        frame = Frame(FrameType.CMD_START, payload)
        encoded = frame.encode()
        decoded = Frame.decode(encoded)
        assert decoded.type == FrameType.CMD_START
        assert decoded.payload == payload

    def test_frame_max_payload(self):
        payload = b'x' * 1024
        frame = Frame(FrameType.EVT_DATA_CHUNK, payload)
        encoded = frame.encode()
        decoded = Frame.decode(encoded)
        assert decoded.payload == payload

    def test_crc_validation(self):
        frame = Frame(FrameType.CMD_START, b'test')
        encoded = bytearray(frame.encode())
        encoded[5] ^= 0xFF
        with pytest.raises(ValueError, match="CRC mismatch"):
            Frame.decode(bytes(encoded))

    def test_framing_validation(self):
        bad = bytearray(b'\x00' + bytes(Frame(FrameType.CMD_PING, b'').encode())[1:])
        with pytest.raises(ValueError, match="Invalid SOF"):
            Frame.decode(bytes(bad))

        bad = bytearray(Frame(FrameType.CMD_PING, b'').encode()[:-1] + b'\x00')
        with pytest.raises(ValueError, match="Invalid SOF/EOF"):
            Frame.decode(bytes(bad))

    def test_payload_length_validation(self):
        payload = b'test'
        frame = Frame(FrameType.CMD_START, payload)
        encoded = bytearray(frame.encode())
        encoded[2] = 0xFF
        encoded[3] = 0xFF
        with pytest.raises(ValueError, match="Invalid payload length"):
            Frame.decode(bytes(encoded))


class TestCmdStart:
    def test_encode_decode(self):
        cmd = CmdStart(
            sample_rate_hz=10_000_000,
            num_samples=100_000,
            trigger_mode=TriggerMode.EDGE,
            trigger_channel=0,
            trigger_edge=TriggerEdge.RISING,
        )
        encoded = cmd.encode()
        assert len(encoded) == 28
        import struct
        rate, samples = struct.unpack('<II', encoded[:8])
        assert rate == 10_000_000
        assert samples == 100_000


class TestFrameStreamDecoder:
    def test_single_frame(self):
        decoder = FrameStreamDecoder()
        frame = Frame(FrameType.CMD_START, b'test')
        frames = list(decoder.feed(frame.encode()))
        assert len(frames) == 1
        assert frames[0].type == FrameType.CMD_START

    def test_multiple_frames(self):
        decoder = FrameStreamDecoder()
        data = Frame(FrameType.CMD_START, b'a').encode() + Frame(FrameType.CMD_STOP, b'').encode()
        frames = list(decoder.feed(data))
        assert len(frames) == 2
        assert frames[0].type == FrameType.CMD_START
        assert frames[1].type == FrameType.CMD_STOP

    def test_fragmented_frames(self):
        decoder = FrameStreamDecoder()
        frame = Frame(FrameType.CMD_START, b'test payload')
        encoded = frame.encode()
        frames = list(decoder.feed(encoded[:10]))
        frames += list(decoder.feed(encoded[10:20]))
        frames += list(decoder.feed(encoded[20:]))
        assert len(frames) == 1
        assert frames[0].type == FrameType.CMD_START

    def test_garbage_recovery(self):
        decoder = FrameStreamDecoder()
        garbage = b'\x00\x00\x01\x02\x03'
        frame = Frame(FrameType.CMD_PING, b'').encode()
        frames = list(decoder.feed(garbage + frame))
        assert len(frames) == 1
        assert frames[0].type == FrameType.CMD_PING

    def test_incomplete_frame_buffering(self):
        decoder = FrameStreamDecoder()
        frame = Frame(FrameType.CMD_START, b'x' * 100)
        encoded = frame.encode()
        frames = list(decoder.feed(encoded[:50]))
        assert len(frames) == 0
        frames = list(decoder.feed(encoded[50:]))
        assert len(frames) == 1


class TestFactoryFunctions:
    def test_make_start_frame(self):
        frame = make_start_frame(CmdStart(
            sample_rate_hz=5_000_000,
            num_samples=50_000,
            trigger_mode=TriggerMode.PATTERN,
            trigger_channel=2,
            trigger_edge=TriggerEdge.EITHER,
        ))
        assert frame.type == FrameType.CMD_START
        assert len(frame.payload) == 28

    def test_make_stop_frame(self):
        frame = make_stop_frame()
        assert frame.type == FrameType.CMD_STOP
        assert frame.payload == b''

    def test_make_get_info_frame(self):
        frame = make_get_info_frame()
        assert frame.type == FrameType.CMD_GET_INFO

    def test_make_ping_frame(self):
        frame = make_ping_frame()
        assert frame.type == FrameType.CMD_PING

    def test_parse_frame(self):
        frame = Frame(FrameType.EVT_INFO, b'x' * 40)
        encoded = frame.encode()
        parsed = parse_frame(encoded)
        assert parsed.type == FrameType.EVT_INFO


if __name__ == '__main__':
    pytest.main([__file__, '-v'])