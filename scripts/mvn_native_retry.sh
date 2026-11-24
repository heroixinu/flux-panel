#!/usr/bin/env bash
# Retry only temporary repository/network failures. Preserve compiler exit status.
set -euo pipefail
log="$1"
shift
for attempt in 1 2 3 4; do
  if mvn -B -ntp -U "$@" 2>&1 | tee "$log"; then
    exit 0
  fi
  if [[ "$attempt" == 4 ]] || ! grep -Eiq 'HTTP (Status: )?(429|502|503|504)|status code: (429|502|503|504)|Read timed out|Connection reset|Connection timed out|Temporary failure in name resolution' "$log"; then
    exit 1
  fi
  sleep "$((attempt * 20))"
done
