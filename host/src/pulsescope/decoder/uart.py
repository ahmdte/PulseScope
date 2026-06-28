"""
UART protocol decoder.

Copyright (c) 2024 PulseScope Contributors
SPDX-License-Identifier: MIT
"""
import numpy as np
from typing import List, Optional
from .base import ProtocolDecoder, DecodedFrame

class UARTDecoder(ProtocolDecoder):
    def __init__(self, samples: np.ndarray, sample_rate_hz: int,
                 channel: int, baud: int = 115200,
                 data_bits: int = 8, parity: str = 'none', stop_bits: int = 1,
                 idle_level: int = 1):
        super().__init__(samples, sample_rate_hz)
        self.channel = channel
        self.baud = baud
        self.data_bits = data_bits
        self.parity = parity
        self.stop_bits = stop_bits
        self.idle_level = idle_level
        self.start_level = 1 - idle_level
        self.spp = sample_rate_hz / baud
        if self.spp < 1.5:
            raise ValueError(f"Sample rate too low for baud {baud}: {sample_rate_hz} Hz -> {self.spp:.1f} samples/bit")

    def decode(self) -> List[DecodedFrame]:
        ch_data = self.get_channel(self.channel)
        frames = []

        edges = self.find_edges(self.channel)
        if self.idle_level == 1:
            edges = edges[self._get_level(edges - 1) == 1]
        else:
            edges = edges[self._get_level(edges - 1) == 0]

        for edge in edges:
            frame = self._decode_frame_at(edge)
            if frame:
                frames.append(frame)

        return frames

    def _get_level(self, indices: np.ndarray) -> np.ndarray:
        ch_data = self.get_channel(self.channel)
        levels = np.zeros_like(indices)
        mask = (indices >= 0) & (indices < len(ch_data))
        levels[mask] = ch_data[indices[mask]]
        return levels

    def _decode_frame_at(self, start_edge: int) -> Optional[DecodedFrame]:
        ch_data = self.get_channel(self.channel)
        spp = self.spp

        start_bit_idx = start_edge + int(spp * 0.5)
        if start_bit_idx >= len(ch_data):
            return None
        if ch_data[start_bit_idx] != self.start_level:
            return None

        bits = []
        for i in range(self.data_bits):
            sample_idx = start_edge + int(spp * (1.5 + i))
            if sample_idx >= len(ch_data):
                return None
            bits.append(ch_data[sample_idx])

        parity_bit = None
        if self.parity != 'none':
            sample_idx = start_edge + int(spp * (1.5 + self.data_bits))
            if sample_idx >= len(ch_data):
                return None
            parity_bit = ch_data[sample_idx]

        stop_start = start_edge + int(spp * (1.5 + self.data_bits + (1 if self.parity != 'none' else 0)))
        valid_stop = True
        stop_bits_found = 0
        for i in range(int(self.stop_bits)):
            idx = stop_start + int(spp * i)
            if idx >= len(ch_data) or ch_data[idx] != self.idle_level:
                valid_stop = False
                break
            stop_bits_found += 1

        if not valid_stop or stop_bits_found == 0:
            return None

        end_idx = stop_start + int(spp * self.stop_bits)

        if self.parity == 'even':
            if (sum(bits) + parity_bit) % 2 != 0:
                return None
        elif self.parity == 'odd':
            if (sum(bits) + parity_bit) % 2 == 0:
                return None

        byte_val = sum(b << i for i, b in enumerate(bits))

        return DecodedFrame(
            type='uart',
            start_sample=start_edge,
            end_sample=end_idx,
            start_time=start_edge / self.sample_rate_hz,
            end_time=end_idx / self.sample_rate_hz,
            data={
                'value': byte_val,
                'hex': f'0x{byte_val:02X}',
                'char': chr(byte_val) if 32 <= byte_val <= 126 else '.',
                'bits': bits,
                'parity': parity_bit,
            },
            raw_bits=ch_data[start_edge:end_idx],
            channel=self.channel,
        )