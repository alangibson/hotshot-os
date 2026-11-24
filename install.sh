#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

KERNEL_RELEASE="$(uname -r)"
KERNEL_MAJOR_MINOR="$(printf '%s\n' "${KERNEL_RELEASE}" | sed -n 's/^\([0-9]\+\.[0-9]\+\)\..*/\1/p')"
LINUX_BRANCH="rpi-${KERNEL_MAJOR_MINOR}.y"
WORK_ROOT="${WORK_ROOT:-${HOME}/kernel-work}"
SRC_DIR="${SRC_DIR:-${WORK_ROOT}/linux-rpi-${KERNEL_RELEASE}}"
BUILD_DIR="/lib/modules/${KERNEL_RELEASE}/build"
MODULE_DIR="/lib/modules/${KERNEL_RELEASE}/kernel/drivers/pinctrl"
PATCH_FILE="${PWD}/mcp23s17-iocon-init.patch"
INITRD_IMAGE="/boot/initrd.img-${KERNEL_RELEASE}"
FIRMWARE_INITRAMFS="/boot/firmware/initramfs8"

if [[ "${KERNEL_RELEASE}" == *-rt ]]; then
	FIRMWARE_INITRAMFS="/boot/firmware/initramfs8_rt"
elif [[ "${KERNEL_RELEASE}" == *2712* ]]; then
	FIRMWARE_INITRAMFS="/boot/firmware/initramfs_2712"
fi

run_sudo() {
	if (( EUID == 0 )); then
		"$@"
	else
		sudo "$@"
	fi
}

require_command() {
	local command_name="$1"

	if ! command -v "${command_name}" >/dev/null 2>&1; then
		echo "missing required command: ${command_name}" >&2
		exit 1
	fi
}

install_overlay() {
	local source_file="$1"
	local overlay_name="${source_file%.dts}"
	local output_file="/tmp/${overlay_name}.dtbo"

	echo "building ${source_file}"
	dtc -@ -I dts -O dtb -o "${output_file}" "${source_file}"

	echo "installing /boot/firmware/overlays/${overlay_name}.dtbo"
	run_sudo install -m 0644 "${output_file}" "/boot/firmware/overlays/${overlay_name}.dtbo"
}

install_dependencies() {
	echo "installing build dependencies"
	run_sudo apt update
	run_sudo apt install -y \
		bc \
		bison \
		build-essential \
		device-tree-compiler \
		dwarves \
		flex \
		git \
		libelf-dev \
		libssl-dev \
		"linux-headers-${KERNEL_RELEASE}" \
		xz-utils
}

check_kernel_build_dir() {
	if [[ ! -d "${BUILD_DIR}" ]]; then
		echo "kernel build directory is missing: ${BUILD_DIR}" >&2
		exit 1
	fi
}

fetch_kernel_source() {
	mkdir -p "${WORK_ROOT}"

	if [[ -d "${SRC_DIR}/.git" ]]; then
		echo "using existing Raspberry Pi Linux source: ${SRC_DIR}"
		return
	fi

	if [[ -e "${SRC_DIR}" ]]; then
		echo "source path exists but is not a git checkout: ${SRC_DIR}" >&2
		exit 1
	fi

	echo "cloning Raspberry Pi Linux source branch ${LINUX_BRANCH}"
	git clone --depth 1 --branch "${LINUX_BRANCH}" \
		https://github.com/raspberrypi/linux.git \
		"${SRC_DIR}"
}

patch_mcp23s17_spi_driver() {
	local spi_driver="${SRC_DIR}/drivers/pinctrl/pinctrl-mcp23s08_spi.c"

	if [[ ! -r "${PATCH_FILE}" ]]; then
		echo "patch file is missing: ${PATCH_FILE}" >&2
		exit 1
	fi

	if [[ ! -r "${spi_driver}" ]]; then
		echo "SPI driver source is missing: ${spi_driver}" >&2
		exit 1
	fi

	if grep -q 'mcp23s17_spi_force_sequential_iocon' "${spi_driver}"; then
		echo "MCP23S17 IOCON patch is already applied"
		return
	fi

	echo "applying MCP23S17 IOCON patch"
	git -C "${SRC_DIR}" apply --check "${PATCH_FILE}"
	git -C "${SRC_DIR}" apply "${PATCH_FILE}"
}

build_mcp23s17_spi_module() {
	echo "building patched pinctrl-mcp23s08_spi.ko"
	make -C "${BUILD_DIR}" M="${SRC_DIR}/drivers/pinctrl" \
		CONFIG_PINCTRL_MCP23S08=m \
		CONFIG_PINCTRL_MCP23S08_SPI=m \
		modules

	if [[ ! -s "${SRC_DIR}/drivers/pinctrl/pinctrl-mcp23s08_spi.ko" ]]; then
		echo "patched module was not built" >&2
		exit 1
	fi
}

install_mcp23s17_spi_module() {
	local backup_dir="/root/module-backup-mcp23s08-${KERNEL_RELEASE}-$(date -u +%Y%m%dT%H%M%SZ)"
	local module="pinctrl-mcp23s08_spi.ko"

	echo "backing up current MCP23S17 SPI module to ${backup_dir}"
	run_sudo mkdir -p "${backup_dir}"
	run_sudo cp "${MODULE_DIR}/${module}.xz" "${backup_dir}/"

	echo "installing patched ${module}.xz"
	xz -k -f "${SRC_DIR}/drivers/pinctrl/${module}"
	run_sudo install -m 0644 "${SRC_DIR}/drivers/pinctrl/${module}.xz" "${MODULE_DIR}/${module}.xz"

	echo "updating module dependencies"
	run_sudo depmod -a "${KERNEL_RELEASE}"

	echo "rebuilding initramfs for ${KERNEL_RELEASE}"
	run_sudo update-initramfs -u -k "${KERNEL_RELEASE}"
	run_sudo install -m 0644 "${INITRD_IMAGE}" "${FIRMWARE_INITRAMFS}"
}

require_command sed

[[ "${KERNEL_RELEASE}" == *rpt-rpi* ]] || {
	echo "this installer must run on a Raspberry Pi rpt kernel; got ${KERNEL_RELEASE}" >&2
	exit 1
}

install_dependencies
require_command dtc
require_command git
require_command make
require_command update-initramfs
require_command xz

install_overlay spi0-7cs.dts
install_overlay mcp23s17-spi0-6.dts

echo "installing /boot/firmware/config.txt"
run_sudo install -m 0644 config.txt /boot/firmware/config.txt

check_kernel_build_dir
fetch_kernel_source
patch_mcp23s17_spi_driver
build_mcp23s17_spi_module
install_mcp23s17_spi_module

echo "boot overlays, config, and patched MCP23S17 SPI module installed; reboot required"
