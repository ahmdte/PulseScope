"""
Basic capture example - simple script to capture and save raw data.
"""
import click
from pulsescope.transport import Transport, auto_connect
from pulsescope.capture import Capture, CaptureConfig
from pulsescope.waveform import Waveform


@click.command()
@click.option('--port', '-p', help='Serial port (auto-detect if not specified)')
@click.option('--rate', '-r', default=10_000_000, help='Sample rate in Hz')
@click.option('--samples', '-n', default=100_000, help='Number of samples')
@click.option('--output', '-o', type=click.Path(), help='Output binary file')
@click.option('--vcd', type=click.Path(), help='Export VCD for GTKWave')
@click.option('--csv', type=click.Path(), help='Export CSV')
@click.option('--trigger', type=click.Choice(['off', 'edge', 'pulse', 'pattern']),
              default='edge', help='Trigger mode')
@click.option('--trigger-ch', '-c', default=0, help='Trigger channel (0-3)')
@click.option('--trigger-edge', type=click.Choice(['rising', 'falling', 'either']),
              default='rising', help='Trigger edge')
@click.option('--pre-trigger', default=0, help='Pre-trigger samples')
def main(port, rate, samples, output, vcd, csv, trigger, trigger_ch, trigger_edge, pre_trigger):
    """PulseScope basic capture"""

    # Auto-connect or use specified port
    if port:
        transport = Transport(port)
        if not transport.connect():
            click.echo(f"Failed to connect to {port}")
            return 1
    else:
        transport = auto_connect()
        if not transport:
            click.echo("No PulseScope found!")
            return 1

    click.echo(f"Connected to {transport.port}")
    click.echo(f"Capturing: {rate/1e6:.1f} MS/s, {samples:,} samples")

    # Build config
    from pulsescope.protocol import TriggerMode, TriggerEdge
    trigger_map = {
        'off': TriggerMode.NONE,
        'edge': TriggerMode.EDGE,
        'pulse': TriggerMode.PULSE,
        'pattern': TriggerMode.PATTERN,
    }
    edge_map = {
        'rising': TriggerEdge.RISING,
        'falling': TriggerEdge.FALLING,
        'either': TriggerEdge.EITHER,
    }

    config = CaptureConfig(
        sample_rate_hz=rate,
        num_samples=samples,
        trigger_mode=trigger_map[trigger] if trigger != 'off' else TriggerMode.NONE,
        trigger_channel=trigger_ch,
        trigger_edge=edge_map[trigger_edge],
        pretrigger_samples=pre_trigger,
    )

    # Capture
    capture = Capture(transport)
    try:
        click.echo("Arming trigger..." if trigger != 'off' else "Starting capture...")
        result = capture.start(config, timeout=30.0)

        click.echo(f"Done: {result.num_samples:,} samples in {result.duration_us/1e3:.1f} ms")
        if result.trigger_index is not None:
            click.echo(f"Trigger at sample {result.trigger_index:,}")

        # Save binary
        if output:
            result.save(output)
            click.echo(f"Saved binary to {output}")

        # Export formats
        wf = Waveform.from_capture_result(result)
        if vcd:
            wf.to_vcd(vcd)
            click.echo(f"Exported VCD to {vcd}")
        if csv:
            wf.to_csv(csv)
            click.echo(f"Exported CSV to {csv}")

    except TimeoutError:
        click.echo("Capture timeout - no trigger?")
    except Exception as e:
        click.echo(f"Error: {e}")
    finally:
        transport.disconnect()

    return 0


if __name__ == '__main__':
    main()