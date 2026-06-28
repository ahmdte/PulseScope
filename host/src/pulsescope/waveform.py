"""
PulseScope waveform data model and analysis utilities.

Copyright (c) 2024 PulseScope Contributors
SPDX-License-Identifier: MIT
"""
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict, Any
from pathlib import Path
import json

from .capture import CaptureResult

@dataclass
class Waveform:
    samples: np.ndarray
    sample_rate_hz: int
    trigger_index: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_capture_result(cls, result: CaptureResult) -> 'Waveform':
        return cls(
            samples=result.samples,
            sample_rate_hz=result.sample_rate_hz,
            trigger_index=result.trigger_index,
            metadata=result.metadata,
        )

    @classmethod
    def from_file(cls, path: str) -> 'Waveform':
        data = np.fromfile(path, dtype=np.uint8)
        n = len(data) // 4
        samples = np.zeros((n, 4), dtype=np.uint8)
        for i in range(4):
            samples[:, i] = (data[:n] >> i) & 1
        return cls(samples=samples, sample_rate_hz=10_000_000)

    def save(self, path: str):
        packed = np.zeros(len(self.samples), dtype=np.uint8)
        for i in range(4):
            packed |= (self.samples[:, i] & 1) << i
        packed.tofile(path)

    def save_json(self, path: str):
        data = {
            'sample_rate_hz': self.sample_rate_hz,
            'trigger_index': self.trigger_index,
            'samples': self.samples.tolist(),
            'metadata': self.metadata,
        }
        with open(path, 'w') as f:
            json.dump(data, f)

    @property
    def num_samples(self) -> int:
        return self.samples.shape[0]

    @property
    def num_channels(self) -> int:
        return self.samples.shape[1] if self.samples.ndim > 1 else 1

    @property
    def duration_s(self) -> float:
        return self.num_samples / self.sample_rate_hz

    @property
    def time_array(self) -> np.ndarray:
        return np.arange(self.num_samples) / self.sample_rate_hz

    def get_channel(self, ch: int) -> np.ndarray:
        return self.samples[:, ch]

    def find_edges(self, channel: int, rising: bool = True, falling: bool = True) -> np.ndarray:
        ch_data = self.get_channel(channel).astype(np.int8)
        diff = np.diff(ch_data)
        edges = []
        if rising:
            edges.append(np.where(diff == 1)[0] + 1)
        if falling:
            edges.append(np.where(diff == -1)[0] + 1)
        if edges:
            return np.sort(np.concatenate(edges))
        return np.array([], dtype=int)

    def measure_pulse_width(self, channel: int, high: bool = True) -> np.ndarray:
        edges = self.find_edges(channel)
        if len(edges) < 2:
            return np.array([])

        widths = []
        if high:
            for i in range(0, len(edges) - 1, 2):
                widths.append(edges[i + 1] - edges[i])
        else:
            for i in range(1, len(edges) - 1, 2):
                widths.append(edges[i + 1] - edges[i])

        return np.array(widths) / self.sample_rate_hz

    def measure_frequency(self, channel: int) -> Optional[float]:
        edges = self.find_edges(channel, rising=True, falling=False)
        if len(edges) < 2:
            return None
        periods = np.diff(edges) / self.sample_rate_hz
        return float(np.median(1.0 / periods))

    def measure_duty_cycle(self, channel: int) -> Optional[float]:
        high_widths = self.measure_pulse_width(channel, high=True)
        low_widths = self.measure_pulse_width(channel, high=False)
        if len(high_widths) == 0 or len(low_widths) == 0:
            return None
        period = np.median(high_widths) + np.median(low_widths)
        return float(np.median(high_widths) / period)

    def to_vcd(self, path: str, channel_names: Optional[List[str]] = None):
        if channel_names is None:
            channel_names = [f"CH{i}" for i in range(self.num_channels)]

        with open(path, 'w') as f:
            f.write("$date\n  PulseScope export\n$end\n")
            f.write("$version\n  PulseScope 1.0\n$end\n")
            f.write("$timescale 1ns $end\n")
            f.write("$scope module PulseScope $end\n")

            for i, name in enumerate(channel_names):
                f.write(f"$var wire 1 {chr(97+i)} {name} $end\n")

            f.write("$upscope $end\n")
            f.write("$enddefinitions $end\n")
            f.write("#0\n")
            for i in range(self.num_channels):
                val = self.samples[0, i]
                f.write(f"{val}{chr(97+i)}\n")

            dt_ns = int(1_000_000_000 / self.sample_rate_hz)
            for t in range(1, self.num_samples):
                time_ns = t * dt_ns
                f.write(f"#{time_ns}\n")
                for i in range(self.num_channels):
                    val = self.samples[t, i]
                    prev = self.samples[t-1, i]
                    if val != prev:
                        f.write(f"{val}{chr(97+i)}\n")

    def to_csv(self, path: str, channel_names: Optional[List[str]] = None):
        if channel_names is None:
            channel_names = [f"CH{i}" for i in range(self.num_channels)]

        header = "time_s," + ",".join(channel_names) + "\n"
        times = self.time_array

        with open(path, 'w') as f:
            f.write(header)
            for i in range(self.num_samples):
                row = f"{times[i]:.9f}," + ",".join(str(self.samples[i, ch]) for ch in range(self.num_channels)) + "\n"
                f.write(row)

# ============================================================================
# Protocol Decoders
# ============================================================================
class ProtocolDecoder:
    def __init__(self, samples: np.ndarray, sample_rate_hz: int):
        self.samples = samples
        self.sample_rate_hz = sample_rate_hz
        self.num_samples = samples.shape[0]
        self.num_channels = samples.shape[1] if samples.ndim > 1 else 1

    def get_channel(self, ch: int) -> np.ndarray:
        if self.samples.ndim > 1:
            return self.samples[:, ch]
        return self.samples

    def find_edges(self, channel: int, rising: bool = True, falling: bool = True) -> np.ndarray:
        ch_data = self.get_channel(channel).astype(np.int8)
        diff = np.diff(ch_data)
        edges = []
        if rising:
            edges.append(np.where(diff == 1)[0] + 1)
        if falling:
            edges.append(np.where(diff == -1)[0] + 1)
        if edges:
            return np.sort(np.concatenate(edges))
        return np.array([], dtype=int)

    def decode(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

@dataclass
class DecodedFrame:
    type: str
    start_sample: int
    end_sample: int
    start_time: float
    end_time: float
    data: Dict[str, Any]
    raw_bits: Optional[np.ndarray] = None
    channel: Optional[int] = None

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

        byte_val = sum(b << i for i, b in enumerate(bits))  # LSB first

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

        sda_edges = self.find_edges(self.cs_ch)
        sda_edges = sda_edges[
            (self._get_level(self.cs_ch, sda_edges - 1) == cs_idle) |
            (self._get_level(self.cs_ch, sda_edges) == cs_idle)
        ]

        i = 0
        while i < len(sda_edges) - 1:
            if self._get_level(self.cs_ch, sda_edges[i]) == cs_active:
                start = sda_edges[i]
                for j in range(i + 1, len(sda_edges)):
                    if self._get_level(self.cs_ch, sda_edges[j]) == cs_idle:
                        end = sda_edges[j]
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

        for bit_idx in range(0, len(mosi_bits), self.bits_per_word):
            if bit_idx + self.bits_per_word > len(mosi_bits):
                break

            mosi_word = mosi_bits[bit_idx:bit_idx + self.bits_per_word]
            if self.msb_first:
                mosi_val = sum(b << (self.bits_per_word - 1 - j) for j, b in enumerate(mosi_word))
            else:
                mosi_val = sum(b << j for j, b in enumerate(mosi_word))

            frame_data = {'mosi': mosi_val, 'mosi_hex': f'0x{mosi_val:02X}'}

            if miso is not None and bit_idx < len(miso):
                miso_word = miso[bit_idx:bit_idx + self.bits_per_word]
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
            i += 1

        frames = []
        for start, stop in transactions:
            txn_frames = self._decode_transaction(start, stop)
            frames.extend(txn_frames)

        return frames

    def _decode_transaction(self, start: int, end: int) -> List[DecodedFrame]:
        scl = self.get_channel(self.scl_ch)
        sda = self.get_channel(self.sda_ch)

        scl_edges = self.find_edges(self.scl_ch)
        scl_edges = scl_edges[(scl_edges > start) & (scl_edges < end)]

        rising_edges = scl_edges[scl[scl_edges] == 1]

        frames = []
        byte_bits = []
        bit_start = None

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

                frames.append(DecodedFrame(
                    type='i2c',
                    start_sample=bit_start,
                    end_sample=sample_idx,
                    start_time=bit_start / self.sample_rate_hz,
                    end_time=sample_idx / self.sample_rate_hz,
                    data={
                        'type': 'address' if len(frames) == 0 else 'data',
                        'value': byte_val,
                        'hex': f'0x{byte_val:02X}',
                        'bits': byte_bits,
                        'ack': ack_bit == 0,
                        'rw': 'read' if data_byte[0] == 1 else 'write' if len(frames) == 1 else None,
                    },
                ))

                byte_bits = []
                bit_start = None

        return frames