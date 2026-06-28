"""
PulseScope high-level capture API.

Copyright (c) 2024 PulseScope Contributors
SPDX-License-Identifier: MIT
"""
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Callable, Iterator
import numpy as np

from .transport import Transport
from .protocol import (
    Frame, FrameType, CmdStart, EvtInfo, EvtDataChunk, EvtTriggerHit,
    EvtCaptureDone, Ack, TriggerMode, TriggerEdge, ErrorCode,
    make_start_frame, make_stop_frame, make_get_info_frame, parse_frame,
)

logger = logging.getLogger(__name__)

@dataclass
class CaptureConfig:
    sample_rate_hz: int = 10_000_000
    num_samples: int = 100_000
    trigger_mode: TriggerMode = TriggerMode.EDGE
    trigger_channel: int = 0
    trigger_edge: TriggerEdge = TriggerEdge.RISING
    trigger_pattern: int = 0
    trigger_pulse_min_ns: int = 0
    trigger_pulse_max_ns: int = 0
    pretrigger_samples: int = 0

@dataclass
class CaptureResult:
    samples: np.ndarray
    sample_rate_hz: int
    duration_us: int
    trigger_index: Optional[int] = None
    trigger_timestamp_us: Optional[int] = None
    metadata: dict = field(default_factory=dict)

    @property
    def num_samples(self) -> int:
        return self.samples.shape[0]

    @property
    def channels(self) -> int:
        return self.samples.shape[1] if self.samples.ndim > 1 else 1

    def get_channel(self, ch: int) -> np.ndarray:
        return self.samples[:, ch]

    def get_times(self) -> np.ndarray:
        dt = 1.0 / self.sample_rate_hz
        return np.arange(self.num_samples) * dt

class Capture:
    def __init__(self, transport: Transport):
        self.transport = transport
        self._config: Optional[CaptureConfig] = None
        self._result: Optional[CaptureResult] = None
        self._chunks: List[EvtDataChunk] = []
        self._trigger_hit: Optional[EvtTriggerHit] = None
        self._done_event: Optional[EvtCaptureDone] = None
        self._error: Optional[Exception] = None
        self._receiving = False

        transport.on_data_chunk(self._on_data_chunk)
        transport.on_frame(self._on_frame)
        transport.on_error(self._on_error)

    def _on_data_chunk(self, chunk: EvtDataChunk):
        if not self._receiving:
            return
        self._chunks.append(chunk)

    def _on_frame(self, frame: Frame):
        if not self._receiving:
            return

        if frame.type == FrameType.EVT_TRIGGER_HIT:
            self._trigger_hit = EvtTriggerHit.decode(frame.payload)
        elif frame.type == FrameType.EVT_CAPTURE_DONE:
            self._done_event = EvtCaptureDone.decode(frame.payload)
            self._receiving = False
        elif frame.type == FrameType.EVT_ERROR:
            pass

    def _on_error(self, error: Exception):
        self._error = error
        self._receiving = False

    def start(self, config: CaptureConfig, timeout: float = 10.0) -> CaptureResult:
        self._config = config
        self._reset_state()
        self._receiving = True

        cmd = CmdStart(
            sample_rate_hz=config.sample_rate_hz,
            num_samples=config.num_samples,
            trigger_mode=config.trigger_mode,
            trigger_channel=config.trigger_channel,
            trigger_edge=config.trigger_edge,
            trigger_pattern=config.trigger_pattern,
            trigger_pulse_min_ns=config.trigger_pulse_min_ns,
            trigger_pulse_max_ns=config.trigger_pulse_max_ns,
            pretrigger_samples=config.pretrigger_samples,
        )
        frame = make_start_frame(cmd)

        if not self.transport.send(frame):
            raise RuntimeError("Failed to send START command")

        deadline = time.time() + timeout
        while self._receiving and time.time() < deadline:
            time.sleep(0.01)

        if self._error:
            raise RuntimeError(f"Capture error: {self._error}")

        if self._receiving:
            logger.warning("Capture timeout, sending STOP")
            self.stop()
            raise TimeoutError("Capture did not complete in time")

        return self._build_result()

    def stop(self) -> bool:
        if not self._receiving:
            return True

        frame = make_stop_frame()
        if not self.transport.send(frame):
            return False

        time.sleep(0.1)
        self._receiving = False
        return True

    def _reset_state(self):
        self._chunks.clear()
        self._trigger_hit = None
        self._done_event = None
        self._error = None

    def _build_result(self) -> CaptureResult:
        if not self._chunks:
            raise RuntimeError("No data received")

        self._chunks.sort(key=lambda c: c.sequence)

        all_samples = []
        for chunk in self._chunks:
            chunk_samples = self._unpack_samples(chunk.samples, chunk.sample_count)
            all_samples.append(chunk_samples)

        samples = np.concatenate(all_samples, axis=0)

        expected = self._config.num_samples
        if expected > 0 and len(samples) > expected:
            samples = samples[:expected]

        trigger_idx = None
        trigger_ts = None
        if self._trigger_hit:
            trigger_idx = self._trigger_hit.sample_index
            trigger_ts = self._trigger_hit.timestamp_us

        duration_us = 0
        if self._done_event:
            duration_us = self._done_event.duration_us

        self._result = CaptureResult(
            samples=samples.astype(np.uint8),
            sample_rate_hz=self._config.sample_rate_hz,
            duration_us=duration_us,
            trigger_index=trigger_idx,
            trigger_timestamp_us=trigger_ts,
            metadata={
                'chunks_received': len(self._chunks),
                'trigger_fired': self._trigger_hit is not None,
            }
        )
        return self._result

    @staticmethod
    def _unpack_samples(packed: bytes, count: int) -> np.ndarray:
        arr = np.frombuffer(packed, dtype=np.uint8)
        out = np.zeros((len(arr), 4), dtype=np.uint8)
        out[:, 0] = (arr >> 0) & 1
        out[:, 1] = (arr >> 1) & 1
        out[:, 2] = (arr >> 2) & 1
        out[:, 3] = (arr >> 3) & 1
        return out[:count]

    def get_result(self) -> Optional[CaptureResult]:
        return self._result

def get_device_info(transport: Transport, timeout: float = 5.0) -> Optional[EvtInfo]:
    frame = make_get_info_frame()
    resp = transport.send_and_wait(frame, FrameType.EVT_INFO, timeout)
    if resp:
        return EvtInfo.decode(resp.payload)
    return None

def run_self_test(transport: Transport, timeout: float = 10.0) -> bool:
    frame = make_self_test_frame()
    resp = transport.send_and_wait(frame, FrameType.ACK, timeout)
    if resp and resp.type == FrameType.ACK:
        ack = Ack.decode(resp.payload)
        return ack.status == ErrorCode.OK
    return False