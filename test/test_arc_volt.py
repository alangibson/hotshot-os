#!/usr/bin/env python3
"""Read an MCP3002 ADC from Raspberry Pi SPI0 CE0."""

from __future__ import annotations

import argparse
import sys
import time


SPI_BUS = 0
SPI_DEVICE = 0
SPI_MAX_SPEED_HZ = 1_000_000
SPI_MODE = 0
DEFAULT_VREF = 5


def load_pi_modules():
    try:
        import spidev
    except ImportError as exc:
        raise SystemExit("This script must run on a Raspberry Pi with spidev installed.") from exc

    return spidev


def configure_spi(spi, args: argparse.Namespace) -> None:
    spi.open(args.bus, args.device)
    spi.max_speed_hz = args.speed_hz
    spi.mode = SPI_MODE
    spi.cshigh = False
    spi.no_cs = False


def read_mcp3002(spi, channel: int) -> int:
    if channel not in (0, 1):
        raise ValueError("MCP3002 channel must be 0 or 1")

    command = 0x68 | (channel << 4)
    response = spi.xfer2([command, 0x00])

    return ((response[0] & 0x03) << 8) | response[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read an MCP3002 ADC using Raspberry Pi SPI0 CE0."
    )
    parser.add_argument("-c", "--channel", type=int, choices=(0, 1), default=0)
    parser.add_argument("--bus", type=int, default=SPI_BUS)
    parser.add_argument("--device", type=int, default=SPI_DEVICE)
    parser.add_argument("--speed-hz", type=int, default=SPI_MAX_SPEED_HZ)
    parser.add_argument("--vref", type=float, default=DEFAULT_VREF)
    parser.add_argument("-n", "--samples", type=int, default=1)
    parser.add_argument("--interval", type=float, default=0.1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.samples < 1:
        raise SystemExit("--samples must be at least 1")

    spidev = load_pi_modules()
    spi = spidev.SpiDev()

    try:
        configure_spi(spi, args)

        for index in range(args.samples):
            raw = read_mcp3002(spi, args.channel)
            volts = raw * args.vref / 1023.0
            print(f"sample={index} channel={args.channel} raw={raw} volts={volts:.6f}")

            if index != args.samples - 1:
                time.sleep(args.interval)
    finally:
        spi.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
