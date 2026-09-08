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

# One-time migration path: reuse the already-authorized xySat deploy identity.
# This preserves Gitea authorization while decoupling memory sync from Stack7.
if [[ ! -s "${MEMORY_SYNC_SSH}/ssh_config" ]]; then
  LEGACY_SSH="${BASE_PATH}/service_-_xysat/ssh"
  if [[ -s "${LEGACY_SSH}/ssh_config" && -s "${LEGACY_SSH}/id_ed25519" && -s "${LEGACY_SSH}/known_hosts" ]]; then
    log "migrating existing xySat SSH identity into dedicated memory-sync runtime"
    install -m 0600 -o "${HERMES_UID}" -g "${HERMES_GID}" "${LEGACY_SSH}/id_ed25519" "${MEMORY_SYNC_SSH}/id_ed25519"
    [[ -s "${LEGACY_SSH}/id_ed25519.pub" ]] && \
      install -m 0644 -o "${HERMES_UID}" -g "${HERMES_GID}" "${LEGACY_SSH}/id_ed25519.pub" "${MEMORY_SYNC_SSH}/id_ed25519.pub"
    install -m 0644 -o "${HERMES_UID}" -g "${HERMES_GID}" "${LEGACY_SSH}/known_hosts" "${MEMORY_SYNC_SSH}/known_hosts"
    install -m 0600 -o "${HERMES_UID}" -g "${HERMES_GID}" "${LEGACY_SSH}/ssh_config" "${MEMORY_SYNC_SSH}/ssh_config"
  else
    die "memory-sync SSH identity missing and no reusable legacy xySat identity found at ${LEGACY_SSH}"
  fi
fi

for file in ssh_config id_ed25519 known_hosts; do
  [[ -s "${MEMORY_SYNC_SSH}/${file}" ]] || die "missing ${MEMORY_SYNC_SSH}/${file}"
done

log "memory-sync runtime: ${MEMORY_SYNC_ROOT}"
log "sandbox lifecycle state: ${SANDBOX_STATE}"
log "sidecar images build directly from Stack6 source"
log "legacy xySat runtime has NOT been removed"

cat <<EOF

Maintenance sidecars prepared.

Next:
  docker compose config --quiet
  docker compose up -d --build hermes-sandbox hermes hermes-memory-sync hermes-sandbox-cleanup
  docker compose ps
EOF
