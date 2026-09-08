#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd -- "${STACK_DIR}/.." && pwd -P)"
ENV_FILE="${ROOT_DIR}/.env"
LOCK_FILE="${STACK_DIR}/.lock"
MANIFEST_TOOL="${STACK_DIR}/manifests.py"
PKI_TOOL="${STACK_DIR}/pki.sh"

log()  { printf '  %s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "run as root"
for cmd in docker python3 openssl install ln readlink stat chmod chown; do
  command -v "${cmd}" >/dev/null 2>&1 || die "missing required command: ${cmd}"
done
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"
[[ -x "${MANIFEST_TOOL}" || -f "${MANIFEST_TOOL}" ]] || die "missing ${MANIFEST_TOOL}"
[[ -x "${PKI_TOOL}" || -f "${PKI_TOOL}" ]] || die "missing ${PKI_TOOL}"
[[ -f "${ENV_FILE}" && ! -L "${ENV_FILE}" ]] || die "missing root operational environment: ${ENV_FILE}"

chown 0:0 "${ENV_FILE}"
chmod 0600 "${ENV_FILE}"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

for key in STACKS_ROOT BASE_PATH NETWORK_NAME ROOT_HOSTNAME; do
  [[ -n "${!key:-}" ]] || die "missing ${key} in ${ENV_FILE}"
done
[[ "${STACKS_ROOT}" == /* && "${BASE_PATH}" == /* ]] || die "STACKS_ROOT and BASE_PATH must be absolute"
[[ "${ROOT_DIR}" == "${STACKS_ROOT%/}" ]] || die "worktree must be ${STACKS_ROOT}; current path: ${ROOT_DIR}"
[[ "${STACKS_ROOT%/}" != "${BASE_PATH%/}" ]] || die "STACKS_ROOT and BASE_PATH must differ"
[[ "${NETWORK_NAME}" =~ ^[A-Za-z0-9_.-]+$ ]] || die "NETWORK_NAME contains unsupported characters"

step "Manifest registry"
python3 "${MANIFEST_TOOL}" validate
python3 "${MANIFEST_TOOL}" validate --target
log "current and target dependency graphs are valid"

step "Central environment compatibility links"
while IFS= read -r directory; do
  stack_path="${ROOT_DIR}/${directory}"
  env_link="${stack_path}/.env"
  [[ -d "${stack_path}" ]] || die "manifest directory does not exist: ${stack_path}"

  if [[ -L "${env_link}" ]]; then
    target="$(readlink "${env_link}")"
    [[ "${target}" == "../.env" ]] || die "unexpected symlink target for ${env_link}: ${target}"
    log "${directory}/.env -> ../.env"
  elif [[ -e "${env_link}" ]]; then
    die "${env_link} exists and is not the managed symlink; refusing to replace it"
  else
    ln -s ../.env "${env_link}"
    log "created ${directory}/.env -> ../.env"
  fi
done < <(python3 "${MANIFEST_TOOL}" directories)

step "Platform runtime"
PLATFORM_ROOT="${BASE_PATH%/}/service_-_platform"
PLATFORM_CERT="${PLATFORM_ROOT}/pki/tls.crt"
PLATFORM_KEY="${PLATFORM_ROOT}/pki/tls.key"
install -d -m 0750 -o 0 -g 0 "${BASE_PATH}" "${PLATFORM_ROOT}"
install -d -m 0700 -o 0 -g 0 "${PLATFORM_ROOT}/pki" "${PLATFORM_ROOT}/state"
install -d -m 0750 -o 0 -g 0 "${PLATFORM_ROOT}/logs"
log "runtime: ${PLATFORM_ROOT}"

step "Shared Docker network ${NETWORK_NAME}"
if docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
  driver="$(docker network inspect -f '{{.Driver}}' "${NETWORK_NAME}")"
  [[ "${driver}" == "bridge" ]] || die "${NETWORK_NAME} exists but uses driver ${driver}, expected bridge"
  log "exists and is bridge"
else
  docker network create --driver bridge "${NETWORK_NAME}" >/dev/null
  log "created"
fi

step "Platform PKI"
if [[ ! -e "${PLATFORM_CERT}" && ! -e "${PLATFORM_KEY}" ]]; then
  LEGACY_RUNTIME_CERT="${BASE_PATH%/}/service_-_haproxy/config/casa.lan.crt"
  LEGACY_RUNTIME_KEY="${BASE_PATH%/}/service_-_haproxy/config/casa.lan.key"
  LEGACY_SOURCE_CERT="${ROOT_DIR}/stack1_-_haproxy_web/config/haproxy/casa.lan.crt"
  LEGACY_SOURCE_KEY="${ROOT_DIR}/stack1_-_haproxy_web/config/haproxy/casa.lan.key"

  if [[ -e "${LEGACY_RUNTIME_CERT}" || -e "${LEGACY_RUNTIME_KEY}" ]]; then
    [[ -s "${LEGACY_RUNTIME_CERT}" && -s "${LEGACY_RUNTIME_KEY}" ]] || die "partial legacy HAProxy runtime PKI detected"
    bash "${PKI_TOOL}" import "${LEGACY_RUNTIME_CERT}" "${LEGACY_RUNTIME_KEY}"
    log "adopted existing HAProxy runtime certificate"
  elif [[ -e "${LEGACY_SOURCE_CERT}" || -e "${LEGACY_SOURCE_KEY}" ]]; then
    [[ -s "${LEGACY_SOURCE_CERT}" && -s "${LEGACY_SOURCE_KEY}" ]] || die "partial legacy HAProxy source PKI detected"
    bash "${PKI_TOOL}" import "${LEGACY_SOURCE_CERT}" "${LEGACY_SOURCE_KEY}"
    log "adopted existing HAProxy source certificate"
  else
    bash "${PKI_TOOL}" create
  fi
else
  bash "${PKI_TOOL}" create
fi

{
  printf 'stack=%s\n' "stack0_-_platform"
  printf 'prepared_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >"${LOCK_FILE}"
chmod 0644 "${LOCK_FILE}"

step "Platform preparation complete"
log "lock: ${LOCK_FILE}"
