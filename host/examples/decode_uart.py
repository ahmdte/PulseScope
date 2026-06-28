"""
Decode UART example - decode from file or live capture.
"""
import sys
sys.path.insert(0, 'src')

import click
from pulsescope import Transport, Capture, CaptureConfig, Waveform
from pulsescope.protocol import TriggerMode, TriggerEdge
from pulsescope.decoder import UARTDecoder

@click.command()
@click.option('--file', '-f', type=click.Path(exists=True), help='Input binary file')
@click.option('--port', '-p', help='Serial port (auto-detect if not specified)')
@click.option('--rate', '-r', default=10_000_000, help='Sample rate in Hz')
@click.option('--baud', '-b', default=115200, help='Baud rate')
@click.option('--channel', '-c', default=0, help='Channel to decode')
@click.option('--samples', '-n', default=100_000, help='Samples to capture (if live)')
@click.option('--output', '-o', type=click.Path(), help='Output CSV file')
@click.option('--trigger/--no-trigger', default=True, help='Use UART start bit trigger')
def main(file, port, rate, baud, channel, samples, output, trigger):
    if file:
        # Decode from file
        print(f"Loading {file}...")
        wf = Waveform.from_file(file)
        wf.sample_rate_hz = rate
        print(f"Loaded {print(f"Sample rate: {wf.sample_rate_hz/1e6:.1f} MS/s, Samples: {wf.num_samples:,}")
    else:
        # Live capture
        transport = Transport.auto_connect() if not port else Transport(port)
        if not transport:
            print("No PulseScope found!")
            return 1

        print(f"Connected to {transport.port}")

        config = CaptureConfig(
            sample_rate_hz=rate,
            num_samples=samples,
            trigger_mode=TriggerMode.UART_START if trigger else TriggerMode.EDGE,
            trigger_channel=channel,
            trigger_edge=TriggerEdge.RISING,
        )

        capture = Capture(transport)
        try:
            result = capture.start(config, timeout=10.0)
            wf = Waveform.from_capture_result(result)
        finally:
            transport.disconnect()

    # Decode UART
    spp = rate / baud
    print(f"Decoding UART: {baud} baud, {spp:.1f} samples/bit on CH{channel}")

    decoder = UARTDecoder(wf, channel=channel, baud=baud)
    frames = decoder.decode()

    print(f"\nDecoded {len(frames)} frames:")
    for f in frames:
        print(f"  {f.start_time*1e6:8.2f}us: {f.data['hex']} '{f.data['char']}'")

    # Export CSV
    if output:
        with open(output, 'w') as fp:
            fp.write("time_us,value_hex,value_char\n")
            for f in frames:
                fp.write(f"{f.start_time*1e6:.2f},{f.data['hex']},{f.data['char']}\n")
        print(f"\nExported to {output}")

    return 0

if __name__ == '__main__':
    main()