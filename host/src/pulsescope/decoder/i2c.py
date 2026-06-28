"""
I2C protocol decoder.

Copyright (c) 2024 PulseScope Contributors
SPDX-License-Identifier: MIT
"""
import numpy as np
from typing import List, Optional
from .base import ProtocolDecoder, DecodedFrame

class I2CDecoder(ProtocolDecoder):
    def __init__(self, samples: np.ndarray, sample_rate_hz: int,
                 sda_ch: int, scl_ch: int):
        super().__init__(samples, sample_rate_hz)
        self.sda_ch = sda_ch
        self.scl_ch = scl_ch

    def decode(self) -> List[DecodedFrame]:
        sda = self.get_channel(self.sda_ch)
        scl = self.get_channel(self.scl_ch)

        scl_edges = self.find_edges(self.scl_ch)
        if len(scl_edges) < 4:
            return []

        sda_edges = self.find_edges(self.sda_ch)
        scl_high = scl == 1

        transactions = []
        i = 0
        while i < len(sda_edges):
            edge = sda_edges[i]
            if edge == 0 or edge >= len(scl_high):
                i += 1
                continue

            if scl_high[edge]:
                is_start = sda[edge] == 0 and (edge == 0 or sda[edge - 1] == 1)
                is_stop = sda[edge] == 1 and (edge == 0 or sda[edge - 1] == 0)

                if is_start:
                    for j in range(i + 1, len(sda_edges)):
                        stop_edge = sda_edges[j]
                        if stop_edge < len(scl_high) and scl_high[stop_edge]:
                            if sda[stop_edge] == 1 and sda[stop_edge - 1] == 0:
                                transactions.append((edge, stop_edge))
                                i = j
                                break
                    else:
                        i += 1
                else:
                    i += 1
            else:
                i += 1

        frames = []
        for start, stop in transactions:
            txn_frames = self._decode_transaction(start, stop)
            frames.extend(txn_frames)

        return frames

    def _decode_transaction(self, start: int, end: int) -> List[DecodedFrame]:
        sda = self.get_channel(self.sda_ch)
        scl = self.get_channel(self.scl_ch)

        scl_edges = self.find_edges(self.scl_ch)
        scl_edges = scl_edges[(scl_edges > start) & (scl_edges < end)]

        rising_edges = scl_edges[scl[scl_edges] == 1]

        frames = []
        byte_bits = []
        bit_start = None
        ack_bits = []

        for i, edge in enumerate(rising_edges):
            if i + 1 < len(rising_edges):
                sample_idx = edge + (rising_edges[i + 1] - edge) // 2
            else:
                sample_idx = edge + (end - edge) // 2

            if sample_idx >= len(sda):
                continue

            bit = sda[sample_idx]
            byte_bits.append(bit)

            if bit_start is None:
                bit_start = edge

            if len(byte_bits) == 9:
                data_byte = byte_bits[:8]
                ack_bit = byte_bits[8]

                byte_val = sum(b << (7 - j) for j, b in enumerate(data_byte))

                is_address = len(frames) == 0
                rw_bit = data_byte[0] if is_address else None

                frames.append(DecodedFrame(
                    type='i2c',
                    start_sample=bit_start,
                    end_sample=sample_idx,
                    start_time=bit_start / self.sample_rate_hz,
                    end_time=sample_idx / self.sample_rate_hz,
                    data={
                        'type': 'address' if is_address else 'data',
                        'value': byte_val,
                        'hex': f'0x{byte_val:02X}',
                        'bits': byte_bits,
                        'ack': ack_bit == 0,
                        'rw': 'read' if rw_bit == 1 else 'write' if rw_bit is not None else None,
                    },
                ))

                byte_bits = []
                bit_start = None

        return frames