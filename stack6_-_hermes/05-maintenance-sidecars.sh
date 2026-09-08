#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="${STACK_DIR}/.env"
LOCK_FILE="${STACK_DIR}/.lock"

log() { printf '[maintenance-prepare] %s\n' "$*"; }
die() { printf '[maintenance-prepare] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "run as root"
[[ -f "${ENV_FILE}" ]] || die "missing ${ENV_FILE}"
[[ -f "${LOCK_FILE}" ]] || die "Stack6 is not prepared; run 01-prepare.sh first"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

required=(BASE_PATH HERMES_UID HERMES_GID MEMORY_SYNC_SERVICE SANDBOX_SERVICE)
for key in "${required[@]}"; do
  [[ -n "${!key:-}" ]] || die "missing ${key} in .env"
done

MEMORY_SYNC_ROOT="${BASE_PATH}/${MEMORY_SYNC_SERVICE}"
MEMORY_SYNC_SSH="${MEMORY_SYNC_ROOT}/ssh"
SANDBOX_STATE="${BASE_PATH}/${SANDBOX_SERVICE}/data/state"

install -d -m 0750 -o "${HERMES_UID}" -g "${HERMES_GID}" "${MEMORY_SYNC_ROOT}"
install -d -m 0700 -o "${HERMES_UID}" -g "${HERMES_GID}" "${MEMORY_SYNC_SSH}"
install -d -m 0700 -o 0 -g 0 "${SANDBOX_STATE}"

# The memory-sync sidecar owns a dedicated, already-authorized SSH identity.
# Preparation never creates, copies or replaces credentials implicitly.
for file in ssh_config id_ed25519 known_hosts; do
  [[ -s "${MEMORY_SYNC_SSH}/${file}" ]] || \
    die "missing dedicated memory-sync SSH material: ${MEMORY_SYNC_SSH}/${file}"
done

log "memory-sync runtime: ${MEMORY_SYNC_ROOT}"
log "sandbox lifecycle state: ${SANDBOX_STATE}"
log "sidecar images build directly from Stack6 source"

cat <<EOF

Maintenance sidecars prepared.

Git memory remains opt-in. To enable only the memory-sync sidecar after 04-gitmem.sh:
  docker compose --profile git-memory up -d --build hermes-memory-sync
  docker compose --profile git-memory ps

The default Stack6 deployment remains:
  docker compose up -d --build
  docker compose ps
EOF
