"""
CAN protocol decoder (placeholder for future implementation).

Copyright (c) 2024 PulseScope Contributors
SPDX-License-Identifier: MIT
"""
from typing import List
from .base import ProtocolDecoder, DecodedFrame
import numpy as np

class CANDecoder(ProtocolDecoder):
    def __init__(self, samples: np.ndarray, sample_rate_hz: int,
                 rx_ch: int, tx_ch: Optional[int] = None,
                 bitrate: int = 500_000):
        super().__init__(samples, sample_rate_hz)
        self.rx_ch = rx_ch
        self.tx_ch = tx_ch
        self.bitrate = bitrate

    def decode(self) -> List[DecodedFrame]:
        # TODO: Implement CAN frame decoding
        # Requires: NRZ bit stuffing removal, frame format (standard/extended),
        # CRC verification, ACK handling
        return []