#!/usr/bin/env bash
set -euo pipefail

SPI_DEVICE="${1:-spi0.6}"
SPI_BUS="${SPI_DEVICE#spi}"
SPI_BUS="${SPI_BUS%%.*}"
SPI_CS="${SPI_DEVICE#*.}"
RESTORE_KERNEL_DRIVER=0

find_gpiochip() {
    local chip
    local major_minor
    local major_hex
    local minor_hex
    local major
    local minor
    local sys_path

    for chip in /dev/gpiochip*; do
        [[ -e "${chip}" && ! -L "${chip}" ]] || continue

        major_minor="$(stat -c '%t:%T' "${chip}")"
        major_hex="${major_minor%:*}"
        minor_hex="${major_minor#*:}"
        major="$((16#${major_hex}))"
        minor="$((16#${minor_hex}))"
        sys_path="$(readlink -f "/sys/dev/char/${major}:${minor}" 2>/dev/null || true)"

        if [[ "${sys_path}" == *"/${SPI_DEVICE}/gpiochip"* ]]; then
            printf '%s\n' "${chip}"
            return 0
        fi
    done

    return 1
}

pin_name() {
    local offset="$1"

    if (( offset < 8 )); then
        printf 'A%d' "${offset}"
    else
        printf 'B%d' "$((offset - 8))"
    fi
}

print_pin_values() {
    local prefix="$1"
    local value="$2"
    local offset

    for offset in {0..15}; do
        printf '%s%s=%d\n' "${prefix}" "$(pin_name "${offset}")" "$(( (value >> offset) & 1 ))"
    done
}

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

read_raw_registers() {
    python3 - "${SPI_BUS}" "${SPI_CS}" <<'PY'
import sys
import spidev

bus = int(sys.argv[1])
cs = int(sys.argv[2])

spi = spidev.SpiDev()
spi.open(bus, cs)
spi.max_speed_hz = 1000

try:
    address = 0
    opcode = 0x40 | (address << 1) | 0x01
    register_names = {
        0x00: "IODIRA",
        0x01: "IODIRB",
        0x0a: "IOCONA",
        0x0b: "IOCONB",
        0x0c: "GPPUA",
        0x0d: "GPPUB",
        0x10: "INTCAPA",
        0x11: "INTCAPB",
        0x12: "GPIOA",
        0x13: "GPIOB",
        0x14: "OLATA",
        0x15: "OLATB",
    }
    registers = {
        name: spi.xfer2([opcode, register, 0x00])[2]
        for register, name in register_names.items()
    }
    gpioa = spi.xfer2([opcode, 0x12, 0x00])[2]
    gpiob = spi.xfer2([opcode, 0x13, 0x00])[2]
    burst = spi.xfer2([opcode, 0x12, 0x00, 0x00])
    base_gpioa = gpioa
    base_gpiob = gpiob
    base_burst_gpioa = burst[2]
    base_burst_gpiob = burst[3]
    address_rows = []
    for address in range(8):
        opcode = 0x40 | (address << 1) | 0x01
        iodira = spi.xfer2([opcode, 0x00, 0x00])[2]
        iodirb = spi.xfer2([opcode, 0x01, 0x00])[2]
        iocona = spi.xfer2([opcode, 0x0a, 0x00])[2]
        ioconb = spi.xfer2([opcode, 0x0b, 0x00])[2]
        gpioa = spi.xfer2([opcode, 0x12, 0x00])[2]
        gpiob = spi.xfer2([opcode, 0x13, 0x00])[2]
        burst = spi.xfer2([opcode, 0x12, 0x00, 0x00])
        address_rows.append(
            (address, opcode, iodira, iodirb, iocona, ioconb, gpioa, gpiob, burst[2], burst[3])
        )
finally:
    spi.close()

for name, value in registers.items():
    print(f"raw_register_{name}=0x{value:02x}")
print(f"raw_single_gpioa=0x{base_gpioa:02x}")
print(f"raw_single_gpiob=0x{base_gpiob:02x}")
print(f"raw_single_combined=0x{((base_gpiob << 8) | base_gpioa):04x}")
print(f"raw_burst_gpioa=0x{base_burst_gpioa:02x}")
print(f"raw_burst_gpiob=0x{base_burst_gpiob:02x}")
print(f"raw_burst_combined=0x{((base_burst_gpiob << 8) | base_burst_gpioa):04x}")
print("address_scan:")
for row in address_rows:
    address, opcode, iodira, iodirb, iocona, ioconb, gpioa, gpiob, burst_a, burst_b = row
    print(
        f"addr={address} opcode=0x{opcode:02x} "
        f"iodir=0x{iodira:02x}/0x{iodirb:02x} "
        f"iocon=0x{iocona:02x}/0x{ioconb:02x} "
        f"single=0x{gpioa:02x}/0x{gpiob:02x} "
        f"burst=0x{burst_a:02x}/0x{burst_b:02x}"
    )
PY
}

if [[ ! -e "/sys/bus/spi/devices/${SPI_DEVICE}" ]]; then
    echo "${SPI_DEVICE} is not present. Confirm spi0-7cs and mcp23s17-spi0-6 overlays are active." >&2
    exit 1
fi

driver_path="$(readlink "/sys/bus/spi/devices/${SPI_DEVICE}/driver" 2>/dev/null || true)"
if [[ "$(basename "${driver_path:-}")" != "mcp23s08" ]]; then
    echo "${SPI_DEVICE} is not bound to the mcp23s08 kernel driver: ${driver_path:-unbound}" >&2
    exit 1
fi

gpiochip="$(find_gpiochip)" || {
    echo "Unable to find MCP23S17 gpiochip for ${SPI_DEVICE}" >&2
    exit 1
}

mapfile -t info_lines < <(gpioinfo --chip "${gpiochip}" | sed -n '2,17p')
read -r -a values < <(gpioget --chip "${gpiochip}" --as-is --numeric 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15)

if (( ${#values[@]} != 16 )); then
    echo "Expected 16 MCP23S17 GPIO values, got ${#values[@]}" >&2
    exit 1
fi

echo "MCP23S17 ${SPI_DEVICE} ${gpiochip}"
echo "kernel_gpio:"

for offset in "${!values[@]}"; do
    printf '%s=%s  %s\n' "$(pin_name "${offset}")" "${values[offset]}" "${info_lines[offset]:-line ${offset}: status unavailable}"
done

echo
echo "raw_spi:"
trap restore_kernel_driver EXIT
bind_spidev
mapfile -t raw_lines < <(read_raw_registers)
restore_kernel_driver
RESTORE_KERNEL_DRIVER=0
trap - EXIT

printf '%s\n' "${raw_lines[@]}"

raw_single_combined=""
raw_burst_combined=""
for line in "${raw_lines[@]}"; do
    case "${line}" in
        raw_single_combined=*) raw_single_combined="${line#*=}" ;;
        raw_burst_combined=*) raw_burst_combined="${line#*=}" ;;
    esac
done

if [[ -n "${raw_single_combined}" ]]; then
    echo "raw_single_pins:"
    print_pin_values "" "$((raw_single_combined))"
fi

if [[ -n "${raw_burst_combined}" ]]; then
    echo "raw_burst_pins:"
    print_pin_values "" "$((raw_burst_combined))"
fi
