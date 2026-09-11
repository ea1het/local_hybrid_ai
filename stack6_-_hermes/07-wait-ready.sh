#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="${STACK_DIR}/.env"
TIMEOUT_SECONDS="${HERMES_READY_TIMEOUT_SECONDS:-240}"
POLL_SECONDS=2

log() { printf '[stack6-ready] %s\n' "$*"; }
die() { printf '[stack6-ready] ERROR: %s\n' "$*" >&2; exit 1; }

[[ -f "${ENV_FILE}" ]] || die "missing ${ENV_FILE}"
command -v docker >/dev/null 2>&1 || die "docker is required"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

for key in HERMES_CONTAINER SANDBOX_CONTAINER SANDBOX_CLEANUP_CONTAINER; do
  [[ -n "${!key:-}" ]] || die "missing ${key} in .env"
done

container_state() {
  local name="$1"
  docker inspect -f '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$name" 2>/dev/null \
    || printf 'absent|\n'
}

is_ready() {
  local raw="$1" status health
  status="${raw%%|*}"
  health="${raw#*|}"
  [[ "${status}" == "running" ]] || return 1
  [[ -z "${health}" || "${health}" == "healthy" ]]
}

containers=("${HERMES_CONTAINER}" "${SANDBOX_CONTAINER}" "${SANDBOX_CLEANUP_CONTAINER}")
start_epoch="$(date +%s)"

while true; do
  ready=true
  summary=()

  for container in "${containers[@]}"; do
    state="$(container_state "${container}")"
    summary+=("${container}=${state/|/\/}")

    case "${state%%|*}" in
      exited|dead|removing|absent)
        die "required runtime failed before READY: ${summary[*]}"
        ;;
    esac

    if ! is_ready "${state}"; then
      ready=false
    fi
  done

  if "${ready}"; then
    log "READY (${summary[*]})"
    exit 0
  fi

  now="$(date +%s)"
  if (( now - start_epoch >= TIMEOUT_SECONDS )); then
    die "required runtime did not become READY within ${TIMEOUT_SECONDS}s: ${summary[*]}"
  fi

  sleep "${POLL_SECONDS}"
done
