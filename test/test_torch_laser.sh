#!/usr/bin/env bash
set -euo pipefail

PIN="${1:-21}"
SECONDS_HIGH="${2:-3}"

cleanup() {
    pinctrl set "${PIN}" op dl
}

trap cleanup EXIT INT TERM

pinctrl set "${PIN}" op dh
sleep "${SECONDS_HIGH}"
cleanup
trap - EXIT INT TERM
