#!/usr/bin/env bash
set -euo pipefail

PIN="${1:-12}"

STATE="$(pinctrl get "${PIN}")"

if [[ "${STATE}" == *" hi "* ]]; then
    echo "1: torch float not triggered"
elif [[ "${STATE}" == *" lo "* ]]; then
    echo "0: torch float triggered"
else
    echo "Unable to read GPIO ${PIN} state: ${STATE}" >&2
    exit 1
fi
