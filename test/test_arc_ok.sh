#!/usr/bin/env bash
set -euo pipefail

PIN="${1:-26}"

STATE="$(pinctrl get "${PIN}")"

if [[ "${STATE}" == *" hi "* ]]; then
    echo "0: Arc is off"
elif [[ "${STATE}" == *" lo "* ]]; then
    echo "1: Arc is on"
else
    echo "Unable to read GPIO ${PIN} state: ${STATE}" >&2
    exit 1
fi
