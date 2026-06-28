"""
PulseScope CLI - Command line interface for host software.

Copyright (c) 2024 PulseScope Contributors
SPDX-License-Identifier: MIT
"""
import sys
import logging
import traceback
from pathlib import Path
from typing import Optional

import click

from .transport import Transport, auto_connect, find_pulsescope_ports
from .capture import Capture, CaptureConfig, get_device_info, run_self_test
from .waveform import Waveform
from .protocol import TriggerMode, TriggerEdge
from .decoder import UARTDecoder, SPIDecoder, I2CDecoder

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('pulsescope')

def get_transport(port: Optional[str]) -> Transport:
    if port:
        transport = Transport(port)
        if not transport.connect():
            click.echo(f"Failed to connect to {port}", err=True)
            sys.exit(1)
        return transport

    click.echo("Auto-detecting PulseScope...")
    transport = auto_connect()
    if transport is None:
        click.echo("No PulseScope found!", err=True)
        sys.exit(1)
    click.echo(f"Connected to {transport.port}")
    return transport

@click.group()
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
@click.option('--port', '-p', help='Serial port (e.g., COM3, /dev/ttyUSB0)')
@click.pass_context
def cli(ctx, verbose, port):
    """PulseScope - 4-channel USB Logic Analyzer"""
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose
    ctx.obj['port'] = port
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

@cli.command()
@click.pass_context
def info(ctx):
    """Show device information"""
    transport = get_transport(ctx.obj['port'])
    info = get_device_info(transport)
    if info:
        click.echo(f"Device:         {info.device_name}")
        click.echo(f"Protocol ver:   {info.protocol_version}")
        click.echo(f"HW version:     {info.hw_version[0]}.{info.hw_version[1]}.{info.hw_version[2]}")
        click.echo(f"FW version:     {info.fw_version >> 16}.{(info.fw_version >> 8) & 0xFF}.{info.fw_version & 0xFF}")
        click.echo(f"Max sample rate: {info.max_sample_rate_hz / 1e6:.1f} MS/s")
        click.echo(f"Max samples:    {info.max_samples:,}")
        click.echo(f"Channels:       {info.num_channels}")
        click.echo(f"Capabilities:   0x{info.capabilities:02X}")
    else:
        click.echo("Failed to get device info", err=True)
    transport.disconnect()

@cli.command()
@click.option('--rate', '-r', default=10_000_000, help='Sample rate in Hz (default: 10 MHz)')
@click.option('--samples', '-n', default=100_000, help='Number of samples to capture (default: 100k)')
@click.option('--trigger-mode', type=click.Choice(['edge', 'pulse', 'pattern', 'uart', 'spi']),
              default='edge', help='Trigger mode')
@click.option('--trigger-channel', '-c', default=0, help='Trigger channel (0-3)')
@click.option('--trigger-edge', type=click.Choice(['rising', 'falling', 'either']),
              default='rising', help='Edge trigger type')
@click.option('--pre-trigger', default=0, help='Pre-trigger samples')
@click.option('--output', '-o', type=click.Path(), help='Output file (binary)')
@click.option('--vcd', type=click.Path(), help='Export VCD for GTKWave')
@click.option('--csv', type=click.Path(), help='Export CSV')
@click.option('--baud', default=115200, help='Baud rate for UART decode')
@click.pass_context
def capture(ctx, rate, samples, trigger_mode, trigger_channel, trigger_edge, pre_trigger, output, vcd, csv, baud):
    """Capture logic signals"""
    transport = get_transport(ctx.obj['port'])

    mode_map = {
        'edge': TriggerMode.EDGE,
        'pulse': TriggerMode.PULSE,
        'pattern': TriggerMode.PATTERN,
        'uart': TriggerMode.UART_START,
        'spi': TriggerMode.SPI_CS,
    }
    edge_map = {
        'rising': TriggerEdge.RISING,
        'falling': TriggerEdge.FALLING,
        'either': TriggerEdge.EITHER,
    }

    config = CaptureConfig(
        sample_rate_hz=rate,
        num_samples=samples,
        trigger_mode=mode_map[trigger_mode],
        trigger_channel=trigger_channel,
        trigger_edge=edge_map[trigger_edge],
        pretrigger_samples=pre_trigger,
    )

    click.echo(f"Starting capture: {rate/1e6:.1f} MS/s, {samples:,} samples")
    click.echo(f"Trigger: {trigger_mode} on CH{trigger_channel} ({trigger_edge})")

    cap = Capture(transport)
    try:
        result = cap.start(config, timeout=30.0)
        click.echo(f"Capture complete: {result.num_samples:,} samples, {result.duration_us/1e3:.1f} ms")

        if result.trigger_index is not None:
            click.echo(f"Trigger at sample {result.trigger_index:,}")

        if output:
            result.save(output)
            click.echo(f"Saved to {output}")

        wf = Waveform.from_capture_result(result)
        if vcd:
            wf.to_vcd(vcd)
            click.echo(f"Exported VCD to {vcd}")
        if csv:
            wf.to_csv(csv)
            click.echo(f"Exported CSV to {csv}")

    except TimeoutError:
        click.echo("Capture timeout!", err=True)
    except Exception as e:
        click.echo(f"Capture error: {e}", err=True)
        if ctx.obj['verbose']:
            traceback.print_exc()
    finally:
        transport.disconnect()

@cli.command()
@click.pass_context
def self_test(ctx):
    """Run device self-test"""
    transport = get_transport(ctx.obj['port'])
    click.echo("Running self-test...")
    if run_self_test(transport):
        click.echo("Self-test PASSED")
    else:
        click.echo("Self-test FAILED", err=True)
    transport.disconnect()

@cli.command()
@click.pass_context
def list_ports(ctx):
    """List available serial ports"""
    ports = find_pulsescope_ports()
    if ports:
        for p in ports:
            click.echo(p)
    else:
        click.echo("No PulseScope devices found")

@cli.command()
@click.argument('file', type=click.Path(exists=True))
@click.option('--rate', '-r', default=10_000_000, help='Sample rate used for capture')
@click.option('--decode', type=click.Choice(['uart', 'spi', 'i2c']), help='Decode protocol')
@click.option('--channel', '-c', default=0, help='Channel to decode')
@click.option('--baud', default=115200, help='Baud rate for UART')
@click.option('--sclk', type=int, help='SCLK channel for SPI')
@click.option('--mosi', type=int, help='MOSI channel for SPI')
@click.option('--miso', type=int, help='MISO channel for SPI')
@click.option('--cs', type=int, help='CS channel for SPI')
@click.option('--sda', type=int, help='SDA channel for I2C')
@click.option('--scl', type=int, help='SCL channel for I2C')
@click.option('--vcd', type=click.Path(), help='Export VCD for GTKWave')
@click.option('--csv', type=click.Path(), help='Export CSV')
@click.pass_context
def analyze(ctx, file, rate, decode, channel, baud, sclk, mosi, miso, cs, sda, scl, vcd, csv):
    """Analyze a captured binary file"""
    click.echo(f"Loading {file}...")
    wf = Waveform.from_file(file)
    wf.sample_rate_hz = rate
    click.echo(f"Loaded {wf.num_samples:,} samples, {wf.num_channels} channels")

    if decode:
        if decode == 'uart':
            decoder = UARTDecoder(wf, channel=channel, baud=baud)
        elif decode == 'spi':
            if None in (sclk, mosi):
                click.echo("SPI decode requires --sclk and --mosi", err=True)
                return
            decoder = SPIDecoder(wf, sclk_ch=sclk, mosi_ch=mosi, miso_ch=miso, cs_ch=cs)
        elif decode == 'i2c':
            if None in (sda, scl):
                click.echo("I2C decode requires --sda and --scl", err=True)
                return
            decoder = I2CDecoder(wf, sda_ch=sda, scl_ch=scl)
        else:
            return

        frames = decoder.decode()
        click.echo(f"\nDecoded {len(frames)} frames:")
        for f in frames[:50]:
            if decode == 'uart':
                click.echo(f"  {f.start_time*1e6:.2f}us: {f.data['hex']} '{f.data['char']}'")
            elif decode == 'spi':
                mosi = f.data.get('mosi_hex', '?')
                miso = f.data.get('miso_hex', '?')
                click.echo(f"  {f.start_time*1e6:.2f}us: MOSI={mosi} MISO={miso}")
            elif decode == 'i2c':
                click.echo(f"  {f.start_time*1e6:.2f}us: {f.data}")

    if vcd:
        wf.to_vcd(vcd)
        click.echo(f"Exported VCD to {vcd}")

    if csv:
        wf.to_csv(csv)
        click.echo(f"Exported CSV to {csv}")

@cli.command()
@click.argument('file', type=click.Path(exists=True))
@click.option('--rate', '-r', default=10_000_000, help='Sample rate in Hz')
@click.option('--vcd', type=click.Path(), help='Export VCD')
@click.option('--csv', type=click.Path(), help='Export CSV')
@click.pass_context
def export(ctx, file, rate, vcd, csv):
    """Export capture to different formats"""
    wf = Waveform.from_file(file)
    wf.sample_rate_hz = rate

    if vcd:
        wf.to_vcd(vcd)
        click.echo(f"Exported VCD to {vcd}")

    if csv:
        wf.to_csv(csv)
        click.echo(f"Exported CSV to {csv}")

def main():
    try:
        cli(obj={})
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()