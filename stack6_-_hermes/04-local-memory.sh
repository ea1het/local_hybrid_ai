#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# Prepare persistent Hermes memory without requiring Git or Stack4.
# Existing data is always preserved. If a Git working tree already exists,
# this script leaves it intact and only validates/creates the two Hermes files.

STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="${STACK_DIR}/.env"
LOCK_FILE="${STACK_DIR}/.lock"

log() { printf '[local-memory] %s\n' "$*"; }
die() { printf '[local-memory] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "run as root"
for cmd in install chown chmod stat sha256sum awk; do
  command -v "${cmd}" >/dev/null 2>&1 || die "missing required command: ${cmd}"
done

[[ -f "${ENV_FILE}" ]] || die "missing ${ENV_FILE}"
[[ -f "${LOCK_FILE}" ]] || die "Stack6 is not PREPARED; run 01-prepare.sh first"

ENV_SHA256_BEFORE="$(sha256sum "${ENV_FILE}" | awk '{print $1}')"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

required=(BASE_PATH HERMES_MEMORY_SERVICE HERMES_UID HERMES_GID)
for key in "${required[@]}"; do
  [[ -n "${!key:-}" ]] || die "missing ${key} in .env"
done

[[ "${BASE_PATH}" == /* ]] || die "BASE_PATH must be absolute"
[[ "${HERMES_MEMORY_SERVICE}" =~ ^service_-_[A-Za-z0-9._-]+$ ]] || die "invalid HERMES_MEMORY_SERVICE"

MEMORY_ROOT="${BASE_PATH%/}/${HERMES_MEMORY_SERVICE}"
MEMORY_DATA="${MEMORY_ROOT}/data"

install -d -m 0750 -o "${HERMES_UID}" -g "${HERMES_GID}" "${MEMORY_ROOT}" "${MEMORY_DATA}"

for file in MEMORY.md USER.md; do
  path="${MEMORY_DATA}/${file}"
  if [[ -e "${path}" ]]; then
    [[ -f "${path}" && ! -L "${path}" ]] || die "${path} must be a regular file"
    log "preserved existing ${file}"
  else
    install -m 0640 -o "${HERMES_UID}" -g "${HERMES_GID}" /dev/null "${path}"
    log "created empty ${file}"
  fi
  chown "${HERMES_UID}:${HERMES_GID}" "${path}"
  chmod 0640 "${path}"
done

chown "${HERMES_UID}:${HERMES_GID}" "${MEMORY_ROOT}" "${MEMORY_DATA}"
chmod 0750 "${MEMORY_ROOT}" "${MEMORY_DATA}"

[[ "$(stat -c '%u:%g:%a' "${MEMORY_DATA}")" == "${HERMES_UID}:${HERMES_GID}:750" ]] || die "unexpected memory directory ownership/mode"
for file in MEMORY.md USER.md; do
  [[ "$(stat -c '%u:%g:%a' "${MEMORY_DATA}/${file}")" == "${HERMES_UID}:${HERMES_GID}:640" ]] || die "unexpected ${file} ownership/mode"
done

ENV_SHA256_AFTER="$(sha256sum "${ENV_FILE}" | awk '{print $1}')"
[[ "${ENV_SHA256_BEFORE}" == "${ENV_SHA256_AFTER}" ]] || die ".env changed during local-memory preparation"

log "persistent local memory ready: ${MEMORY_DATA}"
log "Git is not required; existing .git metadata, if any, was not modified"
