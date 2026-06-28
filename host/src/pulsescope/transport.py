"""
PulseScope transport layer - USB CDC serial communication.

Copyright (c) 2024 PulseScope Contributors
SPDX-License-Identifier: MIT
"""
import serial
import serial.tools.list_ports
import threading
import time
import logging
from typing import Optional, Callable, Iterator, Any
from queue import Queue, Empty
from .protocol import Frame, FrameStreamDecoder, FrameType, ErrorCode

logger = logging.getLogger(__name__)

class Transport:
    BAUDRATE = 115200
    READ_TIMEOUT = 1.0
    WRITE_TIMEOUT = 5.0
    RX_BUFFER_SIZE = 16384

    def __init__(self, port: str):
        self.port = port
        self.serial: Optional[serial.Serial] = None
        self._running = False
        self._rx_thread: Optional[threading.Thread] = None
        self._frame_queue: Queue = Queue(maxsize=1000)
        self._decoder = FrameStreamDecoder()
        self._callbacks = {
            'frame': [],
            'error': [],
            'connected': [],
            'data_chunk': [],
        }
        self._lock = threading.Lock()

    def connect(self) -> bool:
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.BAUDRATE,
                timeout=self.READ_TIMEOUT,
                write_timeout=self.WRITE_TIMEOUT,
            )
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()

            self._running = True
            self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
            self._rx_thread.start()

            logger.info(f"Connected to {self.port}")
            self._emit('connected', True)
            return True
        except Exception as e:
            logger.error(f"Failed to connect to {self.port}: {e}")
            self._emit('error', e)
            return False

    def disconnect(self):
        self._running = False
        if self._rx_thread and self._rx_thread.is_alive():
            self._rx_thread.join(timeout=2.0)
        if self.serial and self.serial.is_open:
            self.serial.close()
        self._emit('connected', False)
        logger.info(f"Disconnected from {self.port}")

    def is_connected(self) -> bool:
        return self.serial is not None and self.serial.is_open and self._running

    def send(self, frame: Frame) -> bool:
        if not self.is_connected():
            return False
        try:
            data = bytes(frame)
            self.serial.write(data)
            self.serial.flush()
            return True
        except Exception as e:
            logger.error(f"Send error: {e}")
            self._emit('error', e)
            return False

    def send_and_wait(self, frame: Frame, expected_response: FrameType,
                      timeout: float = 5.0) -> Optional[Frame]:
        if not self.send(frame):
            return None

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                resp = self._frame_queue.get(timeout=0.1)
                if resp.type == expected_response:
                    return resp
                self._frame_queue.put(resp)
            except Empty:
                continue
        return None

    def on_frame(self, callback: Callable[[Frame], None]):
        self._callbacks['frame'].append(callback)

    def on_error(self, callback: Callable[[Exception], None]):
        self._callbacks['error'].append(callback)

    def on_connected(self, callback: Callable[[bool], None]):
        self._callbacks['connected'].append(callback)

    def on_data_chunk(self, callback: Callable[[Any], None]):
        self._callbacks['data_chunk'].append(callback)

    def _emit(self, event: str, *args):
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args)
            except Exception as e:
                logger.error(f"Callback error ({event}): {e}")

    def _rx_loop(self):
        while self._running and self.serial and self.serial.is_open:
            try:
                waiting = self.serial.in_waiting
                if waiting == 0:
                    time.sleep(0.001)
                    continue

                chunk_size = min(waiting, 4096)
                data = self.serial.read(chunk_size)
                if not data:
                    continue

                for frame in self._decoder.feed(data):
                    self._frame_queue.put(frame)
                    self._emit('frame', frame)

                    if frame.type == FrameType.EVT_DATA_CHUNK:
                        from .protocol import EvtDataChunk
                        chunk = EvtDataChunk.decode(frame.payload)
                        self._emit('data_chunk', chunk)

            except serial.SerialException as e:
                logger.error(f"Serial error: {e}")
                self._emit('error', e)
                break
            except Exception as e:
                logger.error(f"RX loop error: {e}")
                self._emit('error', e)

        self._running = False

    def wait_for_frame(self, timeout: float = 10.0) -> Optional[Frame]:
        try:
            return self._frame_queue.get(timeout=timeout)
        except Empty:
            return None

    def drain_frames(self) -> Iterator[Frame]:
        while True:
            try:
                yield self._frame_queue.get_nowait()
            except Empty:
                break

def find_pulsescope_ports() -> list[str]:
    ports = []
    for port in serial.tools.list_ports.comports():
        if port.vid == 0x303A and port.pid == 0x4001:
            ports.append(port.device)
        elif 'CDC' in (port.description or '').upper():
            ports.append(port.device)
    return ports

def auto_connect() -> Optional[Transport]:
    ports = find_pulsescope_ports()
    if not ports:
        return None

    for port in ports:
        transport = Transport(port)
        if transport.connect():
            from .protocol import make_ping_frame, FrameType
            resp = transport.send_and_wait(make_ping_frame(), FrameType.EVT_PONG, timeout=2.0)
            if resp:
                return transport
            transport.disconnect()
    return None