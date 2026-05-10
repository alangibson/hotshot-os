#!/usr/bin/env bash
set -euo pipefail

OUTPUT_PIN="${1:-15}"
INPUT_PIN="${2:-14}"
SAMPLES="${3:-5}"
INTERVAL_SECONDS="${4:-1}"

cleanup() {
    pinctrl set "${OUTPUT_PIN}" op dl
}

trap cleanup EXIT INT TERM

pinctrl set "${OUTPUT_PIN}" op dh

for ((sample = 1; sample <= SAMPLES; sample++)); do
    STATE="$(pinctrl get "${INPUT_PIN}")"

    if [[ "${STATE}" == *" hi "* ]]; then
        echo "1"
    elif [[ "${STATE}" == *" lo "* ]]; then
        echo "0"
    else
        echo "Unable to read GPIO ${INPUT_PIN} state: ${STATE}" >&2
        exit 1
    fi

    if (( sample < SAMPLES )); then
        sleep "${INTERVAL_SECONDS}"
    fi
done

cleanup
trap - EXIT INT TERM
