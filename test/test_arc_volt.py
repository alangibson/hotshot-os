#!/usr/bin/env python3
"""Read the arc voltage MCP3002 ADC from Raspberry Pi SPI0."""

from __future__ import annotations

import argparse
import sys
import time


SPI_BUS = 0
SPI_DEVICE = 0
# Arc Volt circuit is only stable to 100kHz!
SPI_MAX_SPEED_HZ = 100_000
DEFAULT_SPI_MODE = 0
DEFAULT_VREF = 5.0
DEFAULT_FRAME = "2byte"
DEFAULT_SAMPLES = 20
DEFAULT_DISCARD = 5
DEFAULT_INVERT_MISO = True
DEFAULT_TRIM_POT = 1.235
ARC_VOLT_DIVIDER_RATIO = 1.0 / 50.0


def load_pi_modules():
    try:
        import spidev
    except ImportError as exc:
        raise SystemExit("This script must run on a Raspberry Pi with spidev installed.") from exc

    return spidev


def configure_spi(spi, args: argparse.Namespace) -> None:
    spi.open(args.bus, args.device)
    spi.max_speed_hz = args.speed_hz
    spi.mode = args.mode
    spi.cshigh = False
    spi.no_cs = False


def get_miso_bit(response: list[int], bit_index: int, invert_miso: bool) -> int:
    byte = response[bit_index // 8]
    bit = (byte >> (7 - (bit_index % 8))) & 0x01
    if invert_miso:
        return bit ^ 0x01

    return bit


def assemble_adc_word(
    response: list[int], start_bit: int, width: int, invert_miso: bool
) -> int:
    raw = 0
    for bit_index in range(start_bit, start_bit + width):
        raw = (raw << 1) | get_miso_bit(response, bit_index, invert_miso)

    return raw


def decode_mcp3002_response(
    response: list[int], frame: str, invert_miso: bool
) -> int:
    if frame == "2byte":
        return assemble_adc_word(response, start_bit=6, width=10, invert_miso=invert_miso)

    return assemble_adc_word(response, start_bit=12, width=10, invert_miso=invert_miso)


def read_mcp3002(spi, channel: int, frame: str, invert_miso: bool) -> int:
    if channel not in (0, 1):
        raise ValueError("MCP3002 channel must be 0 or 1")

    if frame == "2byte":
        command = 0x68 | (channel << 4)
        response = spi.xfer2([command, 0x00])
        return decode_mcp3002_response(response, frame, invert_miso)

    response = spi.xfer2([0x01, (0x02 + channel) << 6, 0x00])
    return decode_mcp3002_response(response, frame, invert_miso)


def read_mcp3002_debug(
    spi, channel: int, frame: str, invert_miso: bool
) -> tuple[int, list[int], str]:
    if channel not in (0, 1):
        raise ValueError("MCP3002 channel must be 0 or 1")

    if frame == "2byte":
        command = 0x68 | (channel << 4)
        response = spi.xfer2([command, 0x00])
        raw = decode_mcp3002_response(response, frame, invert_miso)
        decoded_bits = format_adc_bits(response, start_bit=6, width=10, invert_miso=invert_miso)
        return raw, response, decoded_bits

    response = spi.xfer2([0x01, (0x02 + channel) << 6, 0x00])
    raw = decode_mcp3002_response(response, frame, invert_miso)
    decoded_bits = format_adc_bits(response, start_bit=12, width=10, invert_miso=invert_miso)

    return raw, response, decoded_bits


def format_bytes(response: list[int]) -> str:
    return ",".join(f"0x{byte:02x}" for byte in response)


def format_bits(response: list[int]) -> str:
    return "_".join(f"{byte:08b}" for byte in response)


def format_adc_bits(
    response: list[int], start_bit: int, width: int, invert_miso: bool
) -> str:
    return "".join(
        str(get_miso_bit(response, bit_index, invert_miso))
        for bit_index in range(start_bit, start_bit + width)
    )


def ch_to_arc_volts(ch_volts: float) -> float:
    return ch_volts / ARC_VOLT_DIVIDER_RATIO


def apply_trim(ch_volts: float, trim_pot: float) -> float:
    return ch_volts * trim_pot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read the arc voltage MCP3002 ADC using Raspberry Pi SPI0."
    )
    parser.add_argument("-c", "--channel", type=int, choices=(0, 1), default=0)
    parser.add_argument("--bus", type=int, default=SPI_BUS)
    parser.add_argument("--device", type=int, default=SPI_DEVICE)
    parser.add_argument("--speed-hz", type=int, default=SPI_MAX_SPEED_HZ)
    parser.add_argument("--mode", type=int, choices=(0, 1, 2, 3), default=DEFAULT_SPI_MODE)
    parser.add_argument("--vref", type=float, default=DEFAULT_VREF)
    parser.add_argument("--frame", choices=("2byte", "3byte"), default=DEFAULT_FRAME)
    parser.add_argument("--trim-pot", type=float, default=DEFAULT_TRIM_POT)
    parser.add_argument("-n", "--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--discard", type=int, default=DEFAULT_DISCARD)
    parser.add_argument("--interval", type=float, default=0.1)
    parser.add_argument("--debug-raw", action="store_true")
    parser.add_argument(
        "--no-invert-miso",
        dest="invert_miso",
        action="store_false",
        default=DEFAULT_INVERT_MISO,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.samples < 1:
        raise SystemExit("--samples must be at least 1")
    if args.discard < 0:
        raise SystemExit("--discard must be at least 0")
    if args.discard >= args.samples:
        raise SystemExit("--discard must be less than --samples")
    if args.vref <= 0:
        raise SystemExit("--vref must be greater than 0")
    if args.trim_pot <= 0:
        raise SystemExit("--trim-pot must be greater than 0")

    spidev = load_pi_modules()
    spi = spidev.SpiDev()

    try:
        configure_spi(spi, args)

        accepted_raw = []
        for index in range(args.samples):
            if args.debug_raw:
                raw, response, decoded_bits = read_mcp3002_debug(
                    spi, args.channel, args.frame, args.invert_miso
                )
            else:
                raw = read_mcp3002(spi, args.channel, args.frame, args.invert_miso)
                response = []
                decoded_bits = ""

            if index >= args.discard:
                accepted_raw.append(raw)

            untrimmed_ch_volts = raw * args.vref / 1023.0
            ch_volts = apply_trim(untrimmed_ch_volts, args.trim_pot)
            arc_volts = ch_to_arc_volts(ch_volts)
            response_text = ""
            if response:
                response_text = (
                    f" spi_response={format_bytes(response)}"
                    f" spi_bits={format_bits(response)}"
                    f" adc_bits={decoded_bits}"
                )

            print(
                f"sample={index} channel={args.channel} raw={raw} "
                f"CH{args.channel}={ch_volts:.6f} arc_volts={arc_volts:.3f}"
                f"{response_text}"
            )

            if index != args.samples - 1:
                time.sleep(args.interval)

        average_raw = sum(accepted_raw) / len(accepted_raw)
        average_untrimmed_ch_volts = average_raw * args.vref / 1023.0
        average_ch_volts = apply_trim(average_untrimmed_ch_volts, args.trim_pot)
        average_arc_volts = ch_to_arc_volts(average_ch_volts)
        print(
            f"average channel={args.channel} samples={len(accepted_raw)} "
            f"discarded={args.discard} raw={average_raw:.2f} "
            f"trim_pot={args.trim_pot:.6f} "
            f"CH{args.channel}={average_ch_volts:.6f} "
            f"arc_volts={average_arc_volts:.3f}"
        )
    finally:
        spi.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
