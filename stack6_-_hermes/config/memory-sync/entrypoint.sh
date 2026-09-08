#!/usr/bin/env bash
set -Eeuo pipefail

INTERVAL_SECONDS="${MEMORY_SYNC_INTERVAL_SECONDS:-900}"

[[ "${INTERVAL_SECONDS}" =~ ^[0-9]+$ ]] || {
  echo "ERROR: MEMORY_SYNC_INTERVAL_SECONDS must be numeric" >&2
  exit 1
}
(( INTERVAL_SECONDS >= 60 )) || {
  echo "ERROR: MEMORY_SYNC_INTERVAL_SECONDS must be >= 60" >&2
  exit 1
}

run_sync() {
  if ! /usr/local/bin/hermes-memory-sync; then
    echo "[hermes-memory-sync] sync failed; retrying after ${INTERVAL_SECONDS}s" >&2
  fi
}

run_sync

while sleep "${INTERVAL_SECONDS}"; do
  run_sync
done
