"""
PulseScope - 4-channel USB Logic Analyzer host software.

Copyright (c) 2024 PulseScope Contributors
SPDX-License-Identifier: MIT
"""
from .transport import Transport, auto_connect, find_pulsescope_ports
from .capture import Capture, CaptureConfig, CaptureResult, get_device_info, run_self_test
from .waveform import Waveform
from .protocol import (
    Frame, FrameType, CmdStart, EvtDataChunk, EvtTriggerHit,
    TriggerMode, TriggerEdge, ErrorCode,
)

__version__ = '1.0.0'

__all__ = [
    'Transport',
    'auto_connect',
    'find_pulsescope_ports',
    'Capture',
    'CaptureConfig',
    'CaptureResult',
    'get_device_info',
    'run_self_test',
    'Waveform',
    'Frame',
    'FrameType',
    'CmdStart',
    'EvtDataChunk',
    'EvtTriggerHit',
    'TriggerMode',
    'TriggerEdge',
    'ErrorCode',
]