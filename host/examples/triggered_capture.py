"""
Triggered capture example - capture with various trigger modes.
"""
import sys
sys.path.insert(0, 'src')

import numpy as np
from pulsescope import Transport, Capture, CaptureConfig, Waveform
from pulsescope.protocol import TriggerMode, TriggerEdge
from pulsescope.decoder import UARTDecoder

def capture_with_edge_trigger(transport):
    """Edge trigger example"""
    print("=== Edge Trigger (Rising on CH0) ===")
    config = CaptureConfig(
        sample_rate_hz=10_000_000,
        num_samples=50_000,
        trigger_mode=TriggerMode.EDGE,
        trigger_channel=0,
        trigger_edge=TriggerEdge.RISING,
        pretrigger_samples=10_000,  # Capture 10k samples before trigger
    )

    capture = Capture(transport)
    result = capture.start(config, timeout=5.0)
    wf = Waveform.from_capture_result(result)

    if result.trigger_index:
        print(f"Trigger at sample {result.trigger_index} (t={result.trigger_index/result.sample_rate_hz*1e6:.2f}us)")
        # Show samples around trigger
        start = max(0, result.trigger_index - 20)
        end = min(wf.num_samples, result.trigger_index + 20)
        print(f"Samples around trigger:")
        for i in range(start, end):
            t = wf.time_array[i] * 1e6
            marker = " <-- TRIGGER" if i == result.trigger_index else ""
            print(f"  {t:7.2f}us: {wf.samples[i]} {marker}")

    return wf

def capture_with_pulse_trigger(transport):
    """Pulse-width trigger example"""
    print("\n=== Pulse Width Trigger (CH1, 10-100us) ===")
    config = CaptureConfig(
        sample_rate_hz=5_000_000,
        num_samples=200_000,
        trigger_mode=TriggerMode.PULSE,
        trigger_channel=1,
        trigger_edge=TriggerEdge.RISING,  # Use edge for pulse mode
        # Note: pulse width config would go here in full implementation
        pretrigger_samples=50_000,
    )

    capture = Capture(transport)
    result = capture.start(config, timeout=10.0)
    print(f"Captured {result.num_samples} samples")
    return Waveform.from_capture_result(result)

def capture_uart_and_decode(transport):
    """UART capture with auto-decode"""
    print("\n=== UART Capture @ 115200 baud (CH2) ===")
    config = CaptureConfig(
        sample_rate_hz=10_000_000,  # ~87 samples/bit at 115200
        num_samples=200_000,
        trigger_mode=TriggerMode.UART_START,
        trigger_channel=2,
        pretrigger_samples=20_000,
    )

    capture = Capture(transport)
    result = capture.start(config, timeout=10.0)
    wf = Waveform.from_capture_result(result)

    # Auto-decode UART
    decoder = UARTDecoder(wf, channel=2, baud=115200)
    frames = decoder.decode()

    print(f"Decoded {len(frames)} UART frames:")
    for f in frames[:20]:
        print(f"  {f.start_time*1e6:8.1f}us: {f.data['hex']} '{f.data['char']}'")
    if len(frames) > 20:
        print(f"  ... and {len(frames) - 20} more")

    # Save with decode info
    wf.save('uart_capture.bin')
    print("Saved to uart_capture.bin")
    return wf

def capture_spi_and_decode(transport):
    """SPI capture with auto-decode"""
    print("\n=== SPI Capture (CH0=SCLK, CH1=MOSI, CH2=MISO, CH3=CS) ===")
    config = CaptureConfig(
        sample_rate_hz=20_000_000,
        num_samples=100_000,
        trigger_mode=TriggerMode.SPI_CS,
        trigger_channel=3,  # CS on CH3
        pretrigger_samples=5_000,
    )

    capture = Capture(transport)
    result = capture.start(config, timeout=10.0)
    wf = Waveform.from_capture_result(result)

    # Decode SPI
    from pulsescope.decoder import SPIDecoder
    decoder = SPIDecoder(wf, sclk_ch=0, mosi_ch=1, miso_ch=2, cs_ch=3,
                        cpol=0, cpha=0)
    frames = decoder.decode()

    print(f"Decoded {len(frames)} SPI words:")
    for f in frames[:15]:
        print(f"  {f.start_time*1e6:8.1f}us: MOSI={f.data['mosi_hex']} MISO={f.data.get('miso_hex', '?')}")

    return wf

def main():
    transport = Transport.auto_connect()
    if not transport:
        print("No PulseScope found!")
        return 1

    print(f"Connected to {transport.port}")

    try:
        # Run different capture modes
        capture_with_edge_trigger(transport)
        capture_with_pulse_trigger(transport)
        capture_uart_and_decode(transport)
        capture_spi_and_decode(transport)

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        transport.disconnect()

    return 0

if __name__ == '__main__':
    sys.exit(main())