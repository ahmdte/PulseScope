"""
Base protocol decoder classes.

Copyright (c) 2024 PulseScope Contributors
SPDX-License-Identifier: MIT
"""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import numpy as np

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

    def decode(self) -> List[DecodedFrame]:
        raise NotImplementedError

    def _sample_at(self, channel: int, time_s: float) -> int:
        idx = int(time_s * self.sample_rate_hz)
        if 0 <= idx < self.num_samples:
            return self.get_channel(channel)[idx]
        return 0

    def _sample_at_idx(self, channel: int, idx: int) -> int:
        if 0 <= idx < self.num_samples:
            return self.get_channel(channel)[idx]
        return 0