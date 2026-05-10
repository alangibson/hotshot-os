#!/usr/bin/env python3
"""Inspect MCP7940N RTC registers on Raspberry Pi I2C bus 1."""

from __future__ import annotations

import argparse
import fcntl
import glob
import os
import shutil
import subprocess
import sys
import time


I2C_SLAVE_FORCE = 0x0706
DEFAULT_BUS = 1
DEFAULT_ADDRESS = 0x6F

TIMEKEEPING_REGISTERS = {
    0x00: "RTCSEC",
    0x01: "RTCMIN",
    0x02: "RTCHOUR",
    0x03: "RTCWKDAY",
    0x04: "RTCDATE",
    0x05: "RTCMTH",
    0x06: "RTCYEAR",
}

CONTROL_REGISTER = 0x07
SQW_FREQUENCIES = {
    "1hz": 0b00,
    "4096hz": 0b01,
    "8192hz": 0b10,
    "32768hz": 0b11,
}


def bcd_to_int(value: int) -> int:
    return ((value >> 4) * 10) + (value & 0x0F)


class I2CBus:
    def __init__(self, bus: int, address: int) -> None:
        self.path = f"/dev/i2c-{bus}"
        self.address = address
        self.fd: int | None = None

    def __enter__(self) -> "I2CBus":
        self.fd = os.open(self.path, os.O_RDWR)
        fcntl.ioctl(self.fd, I2C_SLAVE_FORCE, self.address)
        return self

    def __exit__(self, *_exc_info: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def read_register(self, register: int) -> int:
        if self.fd is None:
            raise RuntimeError("I2C bus is not open")

        os.write(self.fd, bytes([register]))
        return os.read(self.fd, 1)[0]

    def write_register(self, register: int, value: int) -> None:
        if self.fd is None:
            raise RuntimeError("I2C bus is not open")

        os.write(self.fd, bytes([register, value & 0xFF]))


def read_timekeeping_registers(bus: I2CBus) -> dict[int, int]:
    return {register: bus.read_register(register) for register in TIMEKEEPING_REGISTERS}


def configure_square_wave(bus: I2CBus, frequency: str) -> int:
    value = 0x40 | SQW_FREQUENCIES[frequency]
    bus.write_register(CONTROL_REGISTER, value)
    return bus.read_register(CONTROL_REGISTER)


def disable_square_wave(bus: I2CBus) -> int:
    value = bus.read_register(CONTROL_REGISTER)
    value &= ~0x40
    bus.write_register(CONTROL_REGISTER, value)
    return bus.read_register(CONTROL_REGISTER)


def set_oscillator_start(bus: I2CBus) -> int:
    value = bus.read_register(0x00)
    value |= 0x80
    bus.write_register(0x00, value)
    return bus.read_register(0x00)


def decode_control(value: int) -> list[tuple[str, int, str, str]]:
    sqwfs = value & 0x03
    frequency = {
        0b00: "1 Hz",
        0b01: "4.096 kHz",
        0b10: "8.192 kHz",
        0b11: "32.768 kHz",
    }[sqwfs]

    return [
        ("SQWEN", 1 if value & 0x40 else 0, "MFP square wave enabled", "MFP square wave disabled"),
        ("ALM1EN", 1 if value & 0x20 else 0, "alarm 1 output enabled", "alarm 1 output disabled"),
        ("ALM0EN", 1 if value & 0x10 else 0, "alarm 0 output enabled", "alarm 0 output disabled"),
        ("EXTOSC", 1 if value & 0x08 else 0, "external oscillator input enabled", "crystal oscillator selected"),
        ("CRSTRIM", 1 if value & 0x04 else 0, "coarse trim mode enabled", "normal trim mode"),
        ("SQWFS", sqwfs, f"square wave frequency = {frequency}", f"square wave frequency = {frequency}"),
    ]


def decode_status(registers: dict[int, int]) -> list[tuple[str, bool, str, str]]:
    rtcsec = registers[0x00]
    rtcwkday = registers[0x03]

    return [
        ("ST", bool(rtcsec & 0x80), "oscillator enabled", "oscillator disabled"),
        ("OSCRUN", bool(rtcwkday & 0x20), "oscillator is running", "oscillator is NOT running"),
        ("PWRFAIL", bool(rtcwkday & 0x10), "primary power was lost", "no primary power loss flagged"),
        ("VBATEN", bool(rtcwkday & 0x08), "battery backup enabled", "battery backup disabled"),
    ]


def decode_datetime(registers: dict[int, int]) -> str:
    seconds = bcd_to_int(registers[0x00] & 0x7F)
    minutes = bcd_to_int(registers[0x01] & 0x7F)
    hours = bcd_to_int(registers[0x02] & 0x3F)
    weekday = registers[0x03] & 0x07
    day = bcd_to_int(registers[0x04] & 0x3F)
    month = bcd_to_int(registers[0x05] & 0x1F)
    year = 2000 + bcd_to_int(registers[0x06])

    return (
        f"{year:04d}-{month:02d}-{day:02d} "
        f"{hours:02d}:{minutes:02d}:{seconds:02d} weekday={weekday}"
    )


def print_registers(registers: dict[int, int]) -> None:
    for register, name in TIMEKEEPING_REGISTERS.items():
        value = registers[register]
        print(f"0x{register:02x} {name:<8} = 0x{value:02x} b{value:08b}")


def print_control(value: int) -> None:
    print(f"0x{CONTROL_REGISTER:02x} CONTROL  = 0x{value:02x} b{value:08b}")
    print("control:")
    for name, decoded_value, true_description, false_description in decode_control(value):
        description = true_description if decoded_value else false_description
        print(f"  {name:<7} = {decoded_value}  {description}")


def run_command(label: str, command: list[str]) -> int:
    print(f"\n[{label}]")
    print("$ " + " ".join(command))

    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except FileNotFoundError:
        print(f"{command[0]}: command not found")
        return 127

    output = completed.stdout.rstrip()
    if output:
        print(output)
    else:
        print("(no output)")

    if completed.returncode != 0:
        print(f"exit={completed.returncode}")

    return completed.returncode


def print_path_checks() -> None:
    print("\n[device nodes]")
    for pattern in ("/dev/i2c-1", "/dev/rtc*"):
        matches = sorted(glob.glob(pattern))
        if matches:
            for match in matches:
                stat = os.stat(match)
                print(f"{match} mode={stat.st_mode & 0o777:o} uid={stat.st_uid} gid={stat.st_gid}")
        else:
            print(f"{pattern}: not found")


def print_i2c_scan(bus: int) -> int:
    if shutil.which("i2cdetect"):
        return run_command("i2cdetect", ["i2cdetect", "-y", str(bus)])

    print("\n[i2c scan]")
    print("i2cdetect: command not found; probing known MCP7940N address directly")
    try:
        with I2CBus(bus, DEFAULT_ADDRESS) as i2c_bus:
            i2c_bus.read_register(0x00)
    except OSError as exc:
        print(f"0x{DEFAULT_ADDRESS:02x}: no response ({exc})")
        return 1

    print(f"0x{DEFAULT_ADDRESS:02x}: responds")
    return 0


def print_system_checks(bus: int) -> int:
    print_path_checks()

    print("\n[dmesg rtc]")
    print("$ dmesg | grep -i 'rtc-'")
    try:
        completed = subprocess.run(
            ["dmesg"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except FileNotFoundError:
        print("dmesg: command not found")
    else:
        if completed.returncode != 0:
            print(completed.stdout.rstrip() or f"exit={completed.returncode}")
        else:
            lines = [line for line in completed.stdout.splitlines() if "rtc-" in line.lower()]
            print("\n".join(lines[-80:]) if lines else "(no rtc- lines)")

    return print_i2c_scan(bus)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read and decode MCP7940N RTC timekeeping registers."
    )
    parser.add_argument("--bus", type=int, default=DEFAULT_BUS)
    parser.add_argument(
        "--address",
        type=lambda value: int(value, 0),
        default=DEFAULT_ADDRESS,
        help="I2C address, decimal or hex. Default: 0x6f",
    )
    parser.add_argument(
        "--sample-delay",
        type=float,
        default=3.0,
        help="Seconds to wait before taking a second sample. Use 0 to disable.",
    )
    parser.add_argument(
        "--skip-system-checks",
        action="store_true",
        help="Only read MCP7940N registers; skip device-node, dmesg, and I2C scan checks.",
    )
    parser.add_argument(
        "--enable-sqw",
        choices=sorted(SQW_FREQUENCIES),
        metavar="FREQ",
        help="Configure MFP as square-wave output: 1hz, 4096hz, 8192hz, or 32768hz.",
    )
    parser.add_argument(
        "--disable-sqw",
        action="store_true",
        help="Disable square-wave output on MFP.",
    )
    parser.add_argument(
        "--set-st",
        action="store_true",
        help="Set RTCSEC bit 7 to start the MCP7940N oscillator.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    system_status = 0
    if not args.skip_system_checks:
        system_status = print_system_checks(args.bus)
        print("\n[mcp7940n registers]")

    try:
        with I2CBus(args.bus, args.address) as bus:
            if args.enable_sqw and args.disable_sqw:
                raise SystemExit("--enable-sqw and --disable-sqw are mutually exclusive")

            if args.enable_sqw:
                control = configure_square_wave(bus, args.enable_sqw)
                print(f"configured_mfp_square_wave={args.enable_sqw}")
            elif args.disable_sqw:
                control = disable_square_wave(bus)
                print("configured_mfp_square_wave=disabled")
            else:
                control = bus.read_register(CONTROL_REGISTER)

            if args.set_st:
                rtcsec = set_oscillator_start(bus)
                print(f"set_st=1 RTCSEC=0x{rtcsec:02x} b{rtcsec:08b}")

            first = read_timekeeping_registers(bus)
            second = None

            if args.sample_delay > 0:
                time.sleep(args.sample_delay)
                second = read_timekeeping_registers(bus)
    except FileNotFoundError:
        raise SystemExit(f"/dev/i2c-{args.bus} not found; enable I2C bus {args.bus}.")
    except PermissionError:
        raise SystemExit(
            f"Permission denied opening /dev/i2c-{args.bus}; run with sudo or join the i2c group."
        )
    except OSError as exc:
        raise SystemExit(f"I2C read failed on bus {args.bus} address 0x{args.address:02x}: {exc}")

    print(f"bus=/dev/i2c-{args.bus} address=0x{args.address:02x}")
    print_registers(first)
    print_control(control)
    print(f"decoded_time={decode_datetime(first)}")

    print("status:")
    for name, enabled, true_description, false_description in decode_status(first):
        description = true_description if enabled else false_description
        print(f"  {name:<7} = {int(enabled)}  {description}")

    if second is not None:
        first_seconds = first[0x00] & 0x7F
        second_seconds = second[0x00] & 0x7F
        ticking = first_seconds != second_seconds
        print(f"seconds_changed={int(ticking)} after {args.sample_delay:g}s")

        if not ticking:
            return 1

    if not (first[0x03] & 0x20):
        return 1

    return system_status


if __name__ == "__main__":
    sys.exit(main())
