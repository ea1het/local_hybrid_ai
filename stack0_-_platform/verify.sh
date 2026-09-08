#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd -- "${STACK_DIR}/.." && pwd -P)"
ENV_FILE="${ROOT_DIR}/.env"
LOCK_FILE="${STACK_DIR}/.lock"
MANIFEST_TOOL="${STACK_DIR}/manifests.py"
PKI_TOOL="${STACK_DIR}/pki.sh"

log() { printf '  %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "run as root"
for cmd in docker python3 openssl readlink stat; do
  command -v "${cmd}" >/dev/null 2>&1 || die "missing required command: ${cmd}"
done
[[ -f "${ENV_FILE}" && ! -L "${ENV_FILE}" ]] || die "missing root operational environment: ${ENV_FILE}"
[[ "$(stat -c '%u:%g:%a' "${ENV_FILE}")" == "0:0:600" ]] || die "${ENV_FILE} must be root:root 0600"
[[ -f "${LOCK_FILE}" ]] || die "Stack0 is not prepared: missing ${LOCK_FILE}"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

for key in STACKS_ROOT BASE_PATH NETWORK_NAME ROOT_HOSTNAME; do
  [[ -n "${!key:-}" ]] || die "missing ${key} in ${ENV_FILE}"
done
[[ "${ROOT_DIR}" == "${STACKS_ROOT%/}" ]] || die "worktree path does not match STACKS_ROOT"

python3 "${MANIFEST_TOOL}" validate >/dev/null
python3 "${MANIFEST_TOOL}" validate --target >/dev/null
log "manifest graphs: OK"

while IFS= read -r directory; do
  env_link="${ROOT_DIR}/${directory}/.env"
  [[ -L "${env_link}" ]] || die "missing managed symlink: ${env_link}"
  [[ "$(readlink "${env_link}")" == "../.env" ]] || die "unexpected target for ${env_link}"
done < <(python3 "${MANIFEST_TOOL}" directories)
log "central .env symlinks: OK"

PLATFORM_ROOT="${BASE_PATH%/}/service_-_platform"
for directory in "${PLATFORM_ROOT}" "${PLATFORM_ROOT}/pki" "${PLATFORM_ROOT}/state" "${PLATFORM_ROOT}/logs"; do
  [[ -d "${directory}" && ! -L "${directory}" ]] || die "missing platform runtime directory: ${directory}"
done
log "platform runtime: OK"

docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1 || die "missing Docker network ${NETWORK_NAME}"
[[ "$(docker network inspect -f '{{.Driver}}' "${NETWORK_NAME}")" == "bridge" ]] || die "${NETWORK_NAME} is not a bridge network"
log "shared Docker network: OK"

bash "${PKI_TOOL}" status >/dev/null
log "platform PKI: OK"

printf '\nStack0 READY\n'
