#!/usr/bin/env bash
# =============================================================================
# Prepare Stack7 - xyOps conductor + dedicated xySat worker
# =============================================================================
# Contract:
#   - .env already exists and is complete.
#   - this script NEVER creates, edits or rewrites .env.
#   - if .lock exists, exit immediately without changing anything.
#   - runtime directories are created if missing and otherwise preserved.
#   - xySat config.json is runtime identity/auth state:
#       * it is NEVER created here;
#       * it is NEVER replaced here;
#       * if already enrolled, it must be a non-empty regular file.
#   - no Docker socket, privileged mode or host-root mounts are permitted.
#   - .lock is created only after the complete audit succeeds.
# =============================================================================

set -euo pipefail

STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK_FILE="${STACK_DIR}/.lock"
ENV_FILE="${STACK_DIR}/.env"
COMPOSE_FILE="${STACK_DIR}/docker-compose.yml"

log()  { printf '  %s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
warn() { printf '  AVISO: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# -----------------------------------------------------------------------------
# Lock first
# -----------------------------------------------------------------------------
if [[ -f "${LOCK_FILE}" ]]; then
    printf 'LOCK: %s existe. No se valida ni se modifica nada.\n' "${LOCK_FILE}"
    exit 0
fi

# -----------------------------------------------------------------------------
# Host prerequisites
# -----------------------------------------------------------------------------
[[ "$(id -u)" -eq 0 ]] || die "ejecutar como root"

for cmd in docker grep install chmod stat find sort sha256sum awk touch; do
    command -v "${cmd}" >/dev/null 2>&1 \
        || die "falta el comando requerido: ${cmd}"
done

docker compose version >/dev/null 2>&1 \
    || die "se requiere Docker Compose v2 ('docker compose')"

[[ -f "${ENV_FILE}" ]] \
    || die "falta ${ENV_FILE}; copiar/revisar .env.example antes de preparar"

[[ -f "${COMPOSE_FILE}" ]] \
    || die "falta ${COMPOSE_FILE}"

ENV_SHA256_BEFORE="$(sha256sum "${ENV_FILE}" | awk '{print $1}')"

# -----------------------------------------------------------------------------
# .env contract - read only
# -----------------------------------------------------------------------------
step "Validacion de .env (solo lectura)"

ALL_KEYS=(
    STACKS_ROOT BASE_PATH NETWORK_NAME TZ
    XYOPS_SERVICE XYSAT_SERVICE
    HERMES_MEMORY_SERVICE HERMES_SANDBOX_SERVICE
    XYOPS_CONTAINER XYSAT_CONTAINER
    XYOPS_IMAGE XYOPS_VERSION
    XYSAT_IMAGE XYSAT_VERSION
    XYOPS_HOSTNAME XYOPS_MASTERS XYOPS_BASE_APP_URL
    XYOPS_HTTP_PORT XYOPS_HTTPS_PORT
    XYSAT_CONFIG_FILE
)

for key in "${ALL_KEYS[@]}"; do
    grep -qE "^${key}=" "${ENV_FILE}" \
        || die "falta la variable ${key} en .env"
done

# shellcheck disable=SC1090
set -a
source "${ENV_FILE}"
set +a

for key in "${ALL_KEYS[@]}"; do
    value="${!key:-}"
    [[ -n "${value}" ]] || die "${key} esta vacia en .env"
    [[ "${value}" != CHANGE_ME* ]] \
        || die "${key} sigue usando placeholder: ${value}"
done

[[ "${STACKS_ROOT}" == /* ]] || die "STACKS_ROOT debe ser absoluto"
[[ "${BASE_PATH}" == /* ]] || die "BASE_PATH debe ser absoluto"

STACKS_ROOT="${STACKS_ROOT%/}"
BASE_PATH="${BASE_PATH%/}"

[[ -n "${STACKS_ROOT}" && "${STACKS_ROOT}" != "/" ]] \
    || die "STACKS_ROOT no puede ser /"
[[ -n "${BASE_PATH}" && "${BASE_PATH}" != "/" ]] \
    || die "BASE_PATH no puede ser /"

[[ "${STACK_DIR}" == "${STACKS_ROOT}/stack7_-_xyops" ]] \
    || die "el stack debe residir en ${STACKS_ROOT}/stack7_-_xyops"

for service_var in     XYOPS_SERVICE     XYSAT_SERVICE     HERMES_MEMORY_SERVICE     HERMES_SANDBOX_SERVICE
do
    service_value="${!service_var}"
    [[ "${service_value}" =~ ^service_-_[A-Za-z0-9._-]+$ ]] \
        || die "${service_var} debe seguir el patron service_-_*"
done

[[ "${XYOPS_SERVICE}" != "${XYSAT_SERVICE}" ]] \
    || die "XYOPS_SERVICE y XYSAT_SERVICE deben ser distintos"

[[ "${XYOPS_VERSION}" != "latest" ]] \
    || die "XYOPS_VERSION no puede ser latest"
[[ "${XYSAT_VERSION}" != "latest" ]] \
    || die "XYSAT_VERSION no puede ser latest"
[[ "${XYOPS_IMAGE}" != *:latest ]] \
    || die "XYOPS_IMAGE no puede contener :latest"
[[ "${XYSAT_IMAGE}" != *:latest ]] \
    || die "XYSAT_IMAGE no puede contener :latest"

[[ "${XYOPS_HTTP_PORT}" =~ ^[0-9]+$ ]] \
    || die "XYOPS_HTTP_PORT debe ser numerico"
[[ "${XYOPS_HTTPS_PORT}" =~ ^[0-9]+$ ]] \
    || die "XYOPS_HTTPS_PORT debe ser numerico"

[[ "${XYOPS_HTTP_PORT}" == "5522" ]] \
    || warn "XYOPS_HTTP_PORT no usa el puerto upstream 5522"
[[ "${XYOPS_HTTPS_PORT}" == "5523" ]] \
    || warn "XYOPS_HTTPS_PORT no usa el puerto upstream 5523"

[[ "${XYOPS_BASE_APP_URL}" =~ ^https://[^[:space:]]+$ ]] \
    || die "XYOPS_BASE_APP_URL debe ser una URL https"

[[ "${XYSAT_CONFIG_FILE}" == "/etc/xysat/config.json" ]] \
    || die "XYSAT_CONFIG_FILE debe ser /etc/xysat/config.json"

log ".env completo; no se ha modificado"
log "xyOps fijado a ${XYOPS_IMAGE}:${XYOPS_VERSION}"
log "xySat fijado a ${XYSAT_IMAGE}:${XYSAT_VERSION}"

# -----------------------------------------------------------------------------
# Security contract in Compose
# -----------------------------------------------------------------------------
step "Contrato de seguridad Compose"

if grep -qF '/var/run/docker.sock' "${COMPOSE_FILE}"; then
    die "docker-compose.yml no puede montar /var/run/docker.sock"
fi

if grep -qE '^[[:space:]]*privileged:[[:space:]]*true([[:space:]]|$)' "${COMPOSE_FILE}"; then
    die "docker-compose.yml no puede usar privileged: true"
fi

if grep -qE 'source:[[:space:]]*/opt/docker[[:space:]]*$' "${COMPOSE_FILE}"; then
    die "docker-compose.yml no puede montar /opt/docker completo"
fi

if grep -qE 'XYOPS_xysat_local|XYOPS_XYSAT_LOCAL' "${COMPOSE_FILE}"; then
    die "el conductor no debe arrancar un xySat local"
fi

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" config --quiet \
    || die "docker compose config ha fallado"

docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1 \
    || die "no existe la red Docker externa ${NETWORK_NAME}"

log "Compose y frontera de privilegios: OK"
log "red externa ${NETWORK_NAME}: OK"

# -----------------------------------------------------------------------------
# Runtime paths
# -----------------------------------------------------------------------------
step "Preparacion de runtime"

XYOPS_ROOT="${BASE_PATH}/${XYOPS_SERVICE}"
XYSAT_ROOT="${BASE_PATH}/${XYSAT_SERVICE}"

XYOPS_DATA="${XYOPS_ROOT}/data"
XYOPS_CONF="${XYOPS_ROOT}/conf"
XYOPS_LOGS="${XYOPS_ROOT}/logs"

XYSAT_CONFIG="${XYSAT_ROOT}/config"
XYSAT_LOGS="${XYSAT_ROOT}/logs"
XYSAT_SSH="${XYSAT_ROOT}/ssh"
XYSAT_CONFIG_JSON="${XYSAT_CONFIG}/config.json"

assert_not_symlink() {
    local path="$1"

    if [[ -L "${path}" ]]; then
        die "ruta runtime no puede ser symlink: ${path}"
    fi
}

ensure_directory() {
    local path="$1"
    local mode="$2"

    assert_not_symlink "${path}"

    if [[ -e "${path}" && ! -d "${path}" ]]; then
        die "se esperaba directorio pero existe otro tipo de objeto: ${path}"
    fi

    install -d -m "${mode}" "${path}"
}

ensure_directory "${XYOPS_ROOT}" 0750
ensure_directory "${XYOPS_DATA}" 0750
ensure_directory "${XYOPS_CONF}" 0750
ensure_directory "${XYOPS_LOGS}" 0750

ensure_directory "${XYSAT_ROOT}" 0750
ensure_directory "${XYSAT_CONFIG}" 0700
ensure_directory "${XYSAT_LOGS}" 0750
ensure_directory "${XYSAT_SSH}" 0700

log "runtime xyOps preparado: ${XYOPS_ROOT}"
log "runtime xySat preparado: ${XYSAT_ROOT}"

# -----------------------------------------------------------------------------
# xySat enrollment state
# -----------------------------------------------------------------------------
step "Estado de enrolamiento xySat"

if [[ -L "${XYSAT_CONFIG_JSON}" ]]; then
    die "xySat config.json no puede ser symlink: ${XYSAT_CONFIG_JSON}"
elif [[ -e "${XYSAT_CONFIG_JSON}" ]]; then
    [[ -f "${XYSAT_CONFIG_JSON}" ]] \
        || die "xySat config.json no es fichero regular"

    [[ -s "${XYSAT_CONFIG_JSON}" ]] \
        || die "xySat config.json existe pero esta vacio"

    chmod 0600 "${XYSAT_CONFIG_JSON}"

    log "xySat ya esta enrolado; config.json preservado"
else
    log "xySat aun no esta enrolado"
    log "config.json NO se crea durante prepare"
fi

# -----------------------------------------------------------------------------
# Final filesystem audit
# -----------------------------------------------------------------------------
step "Auditoria final"

for path in \
    "${XYOPS_ROOT}" \
    "${XYOPS_DATA}" \
    "${XYOPS_CONF}" \
    "${XYOPS_LOGS}" \
    "${XYSAT_ROOT}" \
    "${XYSAT_CONFIG}" \
    "${XYSAT_LOGS}" \
    "${XYSAT_SSH}"
do
    [[ -d "${path}" && ! -L "${path}" ]] \
        || die "auditoria runtime fallida: ${path}"
done

ENV_SHA256_AFTER="$(sha256sum "${ENV_FILE}" | awk '{print $1}')"

[[ "${ENV_SHA256_BEFORE}" == "${ENV_SHA256_AFTER}" ]] \
    || die ".env fue modificado durante prepare"

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" config --quiet \
    || die "Compose dejo de ser valido durante prepare"

# Lock only after every validation succeeds.
touch "${LOCK_FILE}"
chmod 0600 "${LOCK_FILE}"

log ".env permanece inalterado"
log "runtime auditado"
log "LOCK creado: ${LOCK_FILE}"

printf '\nStack7 preparado correctamente.\n'
