"""
Tests for PulseScope waveform analysis.

Copyright (c) 2024 PulseScope Contributors
SPDX-License-Identifier: MIT
"""
import pytest
import numpy as np
from pulsescope.waveform import Waveform
from pulsescope.decoder import UARTDecoder, SPIDecoder, I2CDecoder


class TestWaveform:
    @pytest.fixture
    def simple_waveform(self):
        samples = np.zeros((1000, 4), dtype=np.uint8)
        for i in range(1000):
            if (i // 5000) % 2 == 0:
                samples[i, 0] = 1
            samples[i, 1] = 1 - samples[i, 0]
            samples[i, 2] = (i // 100) % 2
            samples[i, 3] = i % 2
        return Waveform(samples=samples, sample_rate_hz=10_000_000)

    def test_properties(self, simple_waveform):
        assert simple_waveform.num_samples == 1000
        assert simple_waveform.num_channels == 4
        assert simple_waveform.duration_s == 0.0001
        assert len(simple_waveform.time_array) == 1000

    def test_get_channel(self, simple_waveform):
        ch0 = simple_waveform.get_channel(0)
        assert len(ch0) == 1000
        assert np.all(ch0[0] == 1)
        assert np.all(ch0[5000] == 0)

    def test_find_edges(self, simple_waveform):
        edges = simple_waveform.find_edges(0, rising=True, falling=True)
        assert len(edges) > 0

    def test_measure_frequency(self, simple_waveform):
        freq = simple_waveform.measure_frequency(0)
        assert freq is not None
        assert abs(freq - 100) < 10

    def test_measure_duty_cycle(self, simple_waveform):
        duty = simple_waveform.measure_duty_cycle(0)
        assert duty is not None
        assert abs(duty - 0.5) < 0.05

    def test_pulse_width(self, simple_waveform):
        widths = simple_waveform.measure_pulse_width(0, high=True)
        assert len(widths) > 0
        expected_width = 5000 / 10_000_000
        for w in widths:
            assert abs(w - expected_width) < 1e-6


class TestUARTDecoder:
    def test_decode_uart_8n1(self):
        rate = 10_000_000
        baud = 115200
        spp = rate / baud

        byte_val = 0x55
        data_bits = [(byte_val >> i) & 1 for i in range(8)]
        frame_bits = [0] + data_bits + [1]
        num_bits = len(frame_bits)

        samples_per_bit = int(spp)
        total_samples = (num_bits + 2) * samples_per_bit
        samples = np.ones((total_samples, 4), dtype=np.uint8)

        for i, bit in enumerate(frame_bits):
            start = (i + 1) * samples_per_bit
            end = start + samples_per_bit
            if end < total_samples:
                samples[start:end, 0] = bit

        wf = Waveform(samples=samples, sample_rate_hz=rate)
        decoder = UARTDecoder(wf, channel=0, baud=baud)
        frames = decoder.decode()

        assert len(frames) >= 1
        assert frames[0].data['value'] == 0x55
        assert frames[0].data['char'] == 'U'

    def test_decode_multiple_bytes(self):
        rate = 10_000_000
        baud = 115200
        spp = rate / baud

        message = b'HELLO'
        frame_bits = []
        for byte in message:
            data_bits = [(byte >> i) & 1 for i in range(8)]
            frame_bits.extend([0] + data_bits + [1])

        samples_per_bit = int(spp)
        total_samples = (len(frame_bits) + 10) * samples_per_bit
        samples = np.ones((total_samples, 4), dtype=np.uint8)

        for i, bit in enumerate(frame_bits):
            start = (i + 1) * samples_per_bit
            end = start + samples_per_bit
            if end < total_samples:
                samples[start:end, 0] = bit

        wf = Waveform(samples=samples, sample_rate_hz=rate)
        decoder = UARTDecoder(wf, channel=0, baud=baud)
        frames = decoder.decode()

        assert len(frames) == 5
        decoded = ''.join(f.data['char'] for f in frames)
        assert decoded == 'HELLO'


class TestSPIDecoder:
    def test_decode_simple_spi(self):
        rate = 10_000_000

        bits = 8
        bits_per_half = 1000
        cycles = 8
        sclk_period = 2 * bits_per_half
        total_samples = 2000 + cycles * sclk_period + 2000

        samples = np.ones((total_samples, 4), dtype=np.uint8)
        idx = 2000

        samples[idx, 3] = 0
        idx += 100

        mosi_byte = 0xAA
        mosi_bits = [(mosi_byte >> (7 - i)) & 1 for i in range(8)]

        for bit in mosi_bits:
            samples[idx, 1] = 1
            samples[idx:idx + bits_per_half, 2] = bit
            idx += bits_per_half

            samples[idx, 1] = 0
            idx += bits_per_half

        samples[idx, 3] = 1

        wf = Waveform(samples=samples, sample_rate_hz=rate)
        decoder = SPIDecoder(wf, sclk_ch=1, mosi_ch=2, cs_ch=3,
                            cpol=0, cpha=0, msb_first=True)
        frames = decoder.decode()

        assert len(frames) > 0


class TestI2CDecoder:
    def test_decode_i2c_address(self):
        rate = 10_000_000
        spp = 1000

        addr = 0x3C << 1
        bits = [(addr >> (7 - i)) & 1 for i in range(8)] + [0]

        samples = np.ones((5000 + 9 * spp * 2, 4), dtype=np.uint8)
        idx = 5000

        sda = samples[:, 0]
        scl = samples[:, 1]

        sda[idx] = 0
        idx += spp

        for bit in bits:
            scl[idx] = 1
            sda[idx] = bit
            idx += spp

            scl[idx] = 0
            idx += spp

        scl[idx] = 1
        sda[idx] = 0
        idx += spp
        sda[idx] = 1

        wf = Waveform(samples=samples, sample_rate_hz=rate)
        decoder = I2CDecoder(wf, sda_ch=0, scl_ch=1)
        frames = decoder.decode()

        assert len(frames) >= 1
        addr_frame = frames[0]
        assert addr_frame.data['type'] == 'address'
        assert addr_frame.data['address'] == 0x3C
        assert addr_frame.data['direction'] == 'write'
        assert addr_frame.data['ack'] is True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])