#!/usr/bin/env bash
set -euo pipefail

PIN="${1:-16}"

STATE="$(pinctrl get "${PIN}")"

if [[ "${STATE}" == *" hi "* ]]; then
    echo "1: Estop not triggered"
elif [[ "${STATE}" == *" lo "* ]]; then
    echo "0: Estop triggered"
else
    echo "Unable to read GPIO ${PIN} state: ${STATE}" >&2
    exit 1
fi
