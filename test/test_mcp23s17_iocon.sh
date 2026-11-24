#!/usr/bin/env bash
set -euo pipefail

SPI_DEVICE="${1:-spi0.6}"
SPI_BUS="${SPI_DEVICE#spi}"
SPI_BUS="${SPI_BUS%%.*}"
SPI_CS="${SPI_DEVICE#*.}"
RESTORE_KERNEL_DRIVER=0

bind_spidev() {
    if [[ -e "/dev/spidev${SPI_BUS}.${SPI_CS}" ]]; then
        return
    fi

    echo "${SPI_DEVICE}" | sudo tee /sys/bus/spi/drivers/mcp23s08/unbind >/dev/null
    echo spidev | sudo tee "/sys/bus/spi/devices/${SPI_DEVICE}/driver_override" >/dev/null
    echo "${SPI_DEVICE}" | sudo tee /sys/bus/spi/drivers/spidev/bind >/dev/null
    RESTORE_KERNEL_DRIVER=1
}

restore_kernel_driver() {
    if (( RESTORE_KERNEL_DRIVER == 0 )); then
        return
    fi

    echo "${SPI_DEVICE}" | sudo tee /sys/bus/spi/drivers/spidev/unbind >/dev/null || true
    printf '\n' | sudo tee "/sys/bus/spi/devices/${SPI_DEVICE}/driver_override" >/dev/null || true
    echo "${SPI_DEVICE}" | sudo tee /sys/bus/spi/drivers/mcp23s08/bind >/dev/null || true
}

if [[ ! -e "/sys/bus/spi/devices/${SPI_DEVICE}" ]]; then
    echo "${SPI_DEVICE} is not present." >&2
    exit 1
fi

trap restore_kernel_driver EXIT
bind_spidev

python3 - "${SPI_BUS}" "${SPI_CS}" <<'PY'
import sys
import time
import spidev

bus = int(sys.argv[1])
cs = int(sys.argv[2])

spi = spidev.SpiDev()
spi.open(bus, cs)
spi.max_speed_hz = 1000
spi.mode = 0

def opcode(addr, read):
    return 0x40 | ((addr & 0x07) << 1) | (1 if read else 0)

def read8(reg, addr=0):
    return spi.xfer2([opcode(addr, True), reg, 0x00])[2]

def write8(reg, value, addr=0):
    spi.xfer2([opcode(addr, False), reg, value & 0xff])
    time.sleep(0.005)

def burst_gpio(addr=0):
    data = spi.xfer2([opcode(addr, True), 0x12, 0x00, 0x00])
    return data[2], data[3]

def snapshot(label):
    bank0 = {
        "IODIRA": read8(0x00),
        "IODIRB": read8(0x01),
        "IOCONA": read8(0x0a),
        "IOCONB": read8(0x0b),
        "GPPUA": read8(0x0c),
        "GPPUB": read8(0x0d),
        "GPIOA": read8(0x12),
        "GPIOB": read8(0x13),
    }
    bank1 = {
        "IOCONA": read8(0x05),
        "IOCONB": read8(0x15),
        "GPIOA": read8(0x09),
        "GPIOB": read8(0x19),
    }
    burst_a, burst_b = burst_gpio()
    print(f"{label}:")
    print(
        "  bank0 "
        + " ".join(f"{name}=0x{value:02x}" for name, value in bank0.items())
        + f" burst=0x{burst_a:02x}/0x{burst_b:02x}"
    )
    print(
        "  bank1 "
        + " ".join(f"{name}=0x{value:02x}" for name, value in bank1.items())
    )

def restore_pullups():
    write8(0x0c, 0xff)
    write8(0x0d, 0xff)

def sequence_patch_current():
    # Current mcp23s17-iocon-init.patch sequence.
    write8(0x0b, 0x80)
    write8(0x05, 0x08)

def sequence_bank0_aliases_haen():
    write8(0x0a, 0x08)
    write8(0x0b, 0x08)

def sequence_bank0_aliases_clear():
    write8(0x0a, 0x00)
    write8(0x0b, 0x00)

def sequence_bank1_aliases_haen():
    write8(0x0b, 0x80)
    write8(0x05, 0x08)
    write8(0x15, 0x08)

def sequence_bank1_to_bank0_no_haen():
    write8(0x0b, 0x80)
    write8(0x05, 0x00)
    write8(0x15, 0x00)

sequences = [
    ("baseline", None),
    ("current_patch_sequence", sequence_patch_current),
    ("bank0_aliases_clear", sequence_bank0_aliases_clear),
    ("bank0_aliases_haen", sequence_bank0_aliases_haen),
    ("bank1_aliases_haen", sequence_bank1_aliases_haen),
    ("bank1_to_bank0_no_haen", sequence_bank1_to_bank0_no_haen),
]

try:
    for name, sequence in sequences:
        if sequence is not None:
            print(f"apply: {name}")
            sequence()
            restore_pullups()
        snapshot(name)
finally:
    restore_pullups()
    spi.close()
PY

restore_kernel_driver
RESTORE_KERNEL_DRIVER=0
trap - EXIT
