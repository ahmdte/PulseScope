"""
SPI protocol decoder.

Copyright (c) 2024 PulseScope Contributors
SPDX-License-Identifier: MIT
"""
import numpy as np
from typing import List, Optional
from .base import ProtocolDecoder, DecodedFrame

class SPIDecoder(ProtocolDecoder):
    def __init__(self, samples: np.ndarray, sample_rate_hz: int,
                 sclk_ch: int, mosi_ch: int,
                 miso_ch: Optional[int] = None, cs_ch: Optional[int] = None,
                 cpol: int = 0, cpha: int = 0, bits_per_word: int = 8,
                 msb_first: bool = True, cs_active_low: bool = True):
        super().__init__(samples, sample_rate_hz)
        self.sclk_ch = sclk_ch
        self.mosi_ch = mosi_ch
        self.miso_ch = miso_ch
        self.cs_ch = cs_ch
        self.cpol = cpol
        self.cpha = cpha
        self.bits_per_word = bits_per_word
        self.msb_first = msb_first
        self.cs_active_low = cs_active_low

        self.sample_edge_rising = (self.cpha == 0 and self.cpol == 0) or (self.cpha == 1 and self.cpol == 1)

    def decode(self) -> List[DecodedFrame]:
        frames = []

        if self.cs_ch is not None:
            frames = self._decode_with_cs()
        else:
            frames = self._decode_continuous()

        return frames

    def _decode_with_cs(self) -> List[DecodedFrame]:
        frames = []
        cs = self.get_channel(self.cs_ch)
        cs_idle = 1 if self.cs_active_low else 0
        cs_active = 1 - cs_idle

        cs_transitions = self.find_edges(self.cs_ch)
        cs_transitions = cs_transitions[
            (self._get_level(self.cs_ch, cs_transitions - 1) == cs_idle) |
            (self._get_level(self.cs_ch, cs_transitions) == cs_idle)
        ]

        i = 0
        while i < len(cs_transitions) - 1:
            if self._get_level(self.cs_ch, cs_transitions[i]) == cs_active:
                start = cs_transitions[i]
                for j in range(i + 1, len(cs_transitions)):
                    if self._get_level(self.cs_ch, cs_transitions[j]) == cs_idle:
                        end = cs_transitions[j]
                        txn_frames = self._decode_transaction(start, end)
                        frames.extend(txn_frames)
                        i = j
                        break
                else:
                    break
            i += 1

        return frames

    def _get_level(self, channel: int, indices: np.ndarray) -> np.ndarray:
        ch_data = self.get_channel(channel)
        levels = np.zeros_like(indices)
        mask = (indices >= 0) & (indices < len(ch_data))
        levels[mask] = ch_data[indices[mask]]
        return levels

    def _decode_continuous(self) -> List[DecodedFrame]:
        return self._decode_transaction(0, self.num_samples)

    def _decode_transaction(self, start: int, end: int) -> List[DecodedFrame]:
        sclk = self.get_channel(self.sclk_ch)
        mosi = self.get_channel(self.mosi_ch)
        miso = self.get_channel(self.miso_ch) if self.miso_ch is not None else None

        edges = self.find_edges(self.sclk_ch)
        edges = edges[(edges >= start) & (edges < end)]

        if len(edges) < 2:
            return []

        frames = []
        mosi_bits = []
        miso_bits = []

        for i, edge in enumerate(edges):
            is_rising = sclk[edge] == 1 and (edge == 0 or sclk[edge - 1] == 0)
            is_falling = sclk[edge] == 0 and (edge == 0 or sclk[edge - 1] == 1)

            is_leading = is_rising if self.cpol == 0 else is_falling
            is_trailing = not is_leading

            if (self.cpha == 0 and is_leading) or (self.cpha == 1 and is_trailing):
                if i + 1 < len(edges):
                    sample_idx = edge + (edges[i + 1] - edge) // 2
                else:
                    sample_idx = edge

                if sample_idx >= len(mosi):
                    continue

                mosi_bits.append(mosi[sample_idx])
                if miso is not None:
                    miso_bits.append(miso[sample_idx])

        for bit_idx in range(0, len(mosi_bits), self.bits_per_word):
            if bit_idx + self.bits_per_word > len(mosi_bits):
                break

            mosi_word = mosi_bits[bit_idx:bit_idx + self.bits_per_word]
            if self.msb_first:
                mosi_val = sum(b << (self.bits_per_word - 1 - j) for j, b in enumerate(mosi_word))
            else:
                mosi_val = sum(b << j for j, b in enumerate(mosi_word))

            frame_data = {'mosi': mosi_val, 'mosi_hex': f'0x{mosi_val:02X}'}

            if miso is not None and bit_idx < len(miso_bits):
                miso_word = miso_bits[bit_idx:bit_idx + self.bits_per_word]
                if len(miso_word) == self.bits_per_word:
                    if self.msb_first:
                        miso_val = sum(b << (self.bits_per_word - 1 - j) for j, b in enumerate(miso_word))
                    else:
                        miso_val = sum(b << j for j, b in enumerate(miso_word))
                    frame_data['miso'] = miso_val
                    frame_data['miso_hex'] = f'0x{miso_val:02X}'

            word_start = edges[bit_idx] if bit_idx < len(edges) else start
            word_end = edges[bit_idx + self.bits_per_word] if bit_idx + self.bits_per_word < len(edges) else end

            frames.append(DecodedFrame(
                type='spi',
                start_sample=word_start,
                end_sample=word_end,
                start_time=word_start / self.sample_rate_hz,
                end_time=word_end / self.sample_rate_hz,
                data=frame_data,
            ))

        return frames