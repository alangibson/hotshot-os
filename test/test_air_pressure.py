#!/usr/bin/env python3
"""Read an air pressure sensor through an MCP3002 on Raspberry Pi SPI0 CE1."""

from __future__ import annotations

import argparse
import sys
import time


SPI_BUS = 0
SPI_DEVICE = 1
MCP3002_CHANNEL = 0
SPI_MAX_SPEED_HZ = 1_000_000
SPI_MODE = 0
DEFAULT_VREF = 3.3
DEFAULT_FRAME = "3byte"
INPUT_DIVIDER_RATIO = 0.6

SENSOR_ZERO_PSI_VOLTS = 0.5
SENSOR_FULL_SCALE_VOLTS = 4.5
SENSOR_FULL_SCALE_PSI = 200.0


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


def read_mcp3002(spi, channel: int, frame: str) -> int:
    if channel not in (0, 1):
        raise ValueError("MCP3002 channel must be 0 or 1")

    if frame == "2byte":
        command = 0x68 | (channel << 4)
        response = spi.xfer2([command, 0x00])
        return ((response[0] & 0x03) << 8) | response[1]

    response = spi.xfer2([0x01, (0x02 + channel) << 6, 0x00])
    return ((response[1] & 0x1F) << 6) | (response[2] >> 2)


def read_mcp3002_debug(spi, channel: int, frame: str) -> tuple[int, list[int]]:
    if channel not in (0, 1):
        raise ValueError("MCP3002 channel must be 0 or 1")

    if frame == "2byte":
        command = 0x68 | (channel << 4)
        response = spi.xfer2([command, 0x00])
        raw = ((response[0] & 0x03) << 8) | response[1]
        return raw, response

    response = spi.xfer2([0x01, (0x02 + channel) << 6, 0x00])
    raw = ((response[1] & 0x1F) << 6) | (response[2] >> 2)

    return raw, response


def volts_to_psi(volts: float) -> float:
    span = SENSOR_FULL_SCALE_VOLTS - SENSOR_ZERO_PSI_VOLTS
    return (volts - SENSOR_ZERO_PSI_VOLTS) * SENSOR_FULL_SCALE_PSI / span


def ch0_to_vin(ch0_volts: float) -> float:
    return ch0_volts / INPUT_DIVIDER_RATIO


def pressure_status(volts: float) -> str:
    if volts < SENSOR_ZERO_PSI_VOLTS:
        return "below_sensor_range"
    if volts > SENSOR_FULL_SCALE_VOLTS:
        return "above_sensor_range"
    return "ok"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read a 0.5-4.5 V, 0-200 PSI air pressure sensor via MCP3002."
    )
    parser.add_argument("--bus", type=int, default=SPI_BUS)
    parser.add_argument("--device", type=int, default=SPI_DEVICE)
    parser.add_argument("--speed-hz", type=int, default=SPI_MAX_SPEED_HZ)
    parser.add_argument("--vref", type=float, default=DEFAULT_VREF)
    parser.add_argument("--frame", choices=("2byte", "3byte"), default=DEFAULT_FRAME)
    parser.add_argument("-n", "--samples", type=int, default=1)
    parser.add_argument("--interval", type=float, default=0.1)
    parser.add_argument("--debug-raw", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.samples < 1:
        raise SystemExit("--samples must be at least 1")
    if args.vref <= 0:
        raise SystemExit("--vref must be greater than 0")

    spidev = load_pi_modules()
    spi = spidev.SpiDev()

    try:
        configure_spi(spi, args)

        for index in range(args.samples):
            if args.debug_raw:
                raw, response = read_mcp3002_debug(spi, MCP3002_CHANNEL, args.frame)
            else:
                raw = read_mcp3002(spi, MCP3002_CHANNEL, args.frame)
                response = []

            ch0_volts = raw * args.vref / 1023.0
            vin = ch0_to_vin(ch0_volts)
            psi = volts_to_psi(vin)
            status = pressure_status(vin)
            response_text = ""
            if response:
                response_text = " response=" + ",".join(f"0x{byte:02x}" for byte in response)

            print(
                f"sample={index} channel={MCP3002_CHANNEL} raw={raw} "
                f"CH0={ch0_volts:.6f} Vin={vin:.6f} psi={psi:.3f} "
                f"status={status}{response_text}"
            )

            if index != args.samples - 1:
                time.sleep(args.interval)
    finally:
        spi.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
