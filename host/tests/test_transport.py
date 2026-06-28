"""
Tests for PulseScope transport layer.

Copyright (c) 2024 PulseScope Contributors
SPDX-License-Identifier: MIT
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
import serial
from pulsescope.transport import Transport, find_pulsescope_ports, auto_connect
from pulsescope.protocol import Frame, FrameType, make_ping_frame


class TestTransport:
    @pytest.fixture
    def transport(self):
        t = Transport('COM1')
        t.serial = MagicMock()
        t.serial.is_open = True
        t.serial.in_waiting = 0
        return t

    def test_connect_success(self, transport):
        with patch('pulsescope.transport.serial.Serial') as mock_serial:
            mock_serial.return_value = transport.serial
            t = Transport('COM1')
            assert t.connect() is True
            assert t.is_connected()

    def test_connect_failure(self):
        with patch('pulsescope.transport.serial.Serial') as mock_serial:
            mock_serial.side_effect = serial.SerialException("Port busy")
            t = Transport('COM1')
            assert t.connect() is False

    def test_disconnect(self, transport):
        transport.disconnect()
        assert not transport.is_connected()
        transport.serial.close.assert_called_once()

    def test_send_frame(self, transport):
        frame = Frame(FrameType.CMD_PING, b'')
        assert transport.send(frame) is True
        transport.serial.write.assert_called_once()
        transport.serial.flush.assert_called_once()

    def test_send_not_connected(self):
        t = Transport('COM1')
        frame = Frame(FrameType.CMD_PING, b'')
        assert t.send(frame) is False

    def test_callbacks(self, transport):
        frame_cb = Mock()
        error_cb = Mock()
        conn_cb = Mock()

        transport.on_frame(frame_cb)
        transport.on_error(error_cb)
        transport.on_connected(conn_cb)

        assert frame_cb in transport._callbacks['frame']
        assert error_cb in transport._callbacks['error']
        assert conn_cb in transport._callbacks['connected']

    def test_emit_callbacks(self, transport):
        called = []

        def frame_cb(f): called.append(('frame', f))
        def error_cb(e): called.append(('error', e))
        def conn_cb(c): called.append(('connected', c))

        transport.on_frame(frame_cb)
        transport.on_error(error_cb)
        transport.on_connected(conn_cb)

        transport._emit('frame', 'test_frame')
        transport._emit('error', 'test_error')
        transport._emit('connected', True)

        assert ('frame', 'test_frame') in called
        assert ('error', 'test_error') in called
        assert ('connected', True) in called


class TestFindPorts:
    def test_find_ports_with_esppid(self):
        with patch('pulsescope.transport.serial.tools.list_ports.comports') as mock:
            mock_port = Mock()
            mock_port.vid = 0x303A
            mock_port.pid = 0x4001
            mock_port.device = 'COM3'
            mock_port.description = 'ESP32-S3 USB CDC'
            mock.return_value = [mock_port]

            ports = find_pulsescope_ports()
            assert 'COM3' in ports

    def test_find_ports_with_cdc(self):
        with patch('pulsescope.transport.serial.tools.list_ports.comports') as mock:
            mock_port = Mock()
            mock_port.vid = 0x1234
            mock_port.pid = 0x5678
            mock_port.device = 'COM4'
            mock_port.description = 'USB CDC Device'
            mock.return_value = [mock_port]

            ports = find_pulsescope_ports()
            assert 'COM4' in ports

    def test_find_ports_none(self):
        with patch('pulsescope.transport.serial.tools.list_ports.comports') as mock:
            mock.return_value = []
            ports = find_pulsescope_ports()
            assert ports == []


class TestAutoConnect:
    def test_auto_connect_success(self):
        with patch('pulsescope.transport.find_pulsescope_ports') as mock_find:
            mock_find.return_value = ['COM3']

            mock_transport = Mock(spec=Transport)
            mock_transport.connect.return_value = True
            mock_transport.send_and_wait.return_value = Frame(FrameType.EVT_PONG, b'')

            with patch('pulsescope.transport.Transport', return_value=mock_transport):
                result = auto_connect()
                assert result == mock_transport
                mock_transport.connect.assert_called_once()
                mock_transport.send_and_wait.assert_called_once()

    def test_auto_connect_no_ports(self):
        with patch('pulsescope.transport.find_pulsescope_ports') as mock_find:
            mock_find.return_value = []
            result = auto_connect()
            assert result is None

    def test_auto_connect_all_fail(self):
        with patch('pulsescope.transport.find_pulsescope_ports') as mock_find:
            mock_find.return_value = ['COM3', 'COM4']

            mock_transport = Mock(spec=Transport)
            mock_transport.connect.return_value = False

            with patch('pulsescope.transport.Transport', return_value=mock_transport):
                result = auto_connect()
                assert result is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])