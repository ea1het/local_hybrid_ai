#!/usr/bin/env bash
set -Eeuo pipefail

STACK_NAME="stack3_-_litellm"
STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="${STACK_DIR}/.env"
COMPOSE_FILE="${STACK_DIR}/docker-compose.yml"
LOCK_FILE="${STACK_DIR}/.lock"

log()  { printf '  %s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

if [[ -e "${LOCK_FILE}" ]]; then
  printf 'Stack ya preparado. Existe %s; no se realiza ningun cambio.\n' "${LOCK_FILE}"
  exit 0
fi

[[ "$(id -u)" -eq 0 ]] || die "ejecuta este script como root"
for cmd in docker openssl install; do
  command -v "${cmd}" >/dev/null 2>&1 || die "${cmd} no esta instalado"
done
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 no esta disponible"
[[ -f "${ENV_FILE}" ]] || die "falta ${ENV_FILE}"
[[ -f "${COMPOSE_FILE}" ]] || die "falta ${COMPOSE_FILE}"

grep -Eq '^[A-Za-z_][A-Za-z0-9_]*=.*(<REDACT|\.{5,})' "${ENV_FILE}" && \
  die "${ENV_FILE} contiene valores saneados/incompletos"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

require_env() { local key="$1"; [[ -n "${!key:-}" ]] || die "falta ${key} en ${ENV_FILE}"; }
for key in STACKS_ROOT BASE_PATH NETWORK_NAME LITELLM_IMAGE LITELLM_VERSION \
           LITELLM_MASTER_KEY LITELLM_SALT_KEY UI_USERNAME UI_PASSWORD \
           STORE_MODEL_IN_DB LITELLM_DB_NAME LITELLM_DB_USER LITELLM_DB_PASSWORD; do
  require_env "${key}"
done

[[ "${STACKS_ROOT}" = /* && "${BASE_PATH}" = /* ]] || die "STACKS_ROOT y BASE_PATH deben ser rutas absolutas"
[[ "${STACK_DIR}" == "${STACKS_ROOT%/}/${STACK_NAME}" ]] || \
  die "este stack debe residir en ${STACKS_ROOT%/}/${STACK_NAME}; ruta actual: ${STACK_DIR}"
[[ "${STACKS_ROOT%/}" != "${BASE_PATH%/}" ]] || die "STACKS_ROOT y BASE_PATH deben ser distintos"
[[ "${LITELLM_IMAGE}" != *:latest ]] || die "LITELLM_IMAGE no debe usar :latest"
[[ "${LITELLM_VERSION}" != "latest" ]] || die "LITELLM_VERSION no puede ser latest"
[[ "${LITELLM_DB_NAME}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "LITELLM_DB_NAME no es valido"
[[ "${LITELLM_DB_USER}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "LITELLM_DB_USER no es valido"

STACK0_LOCK="${STACKS_ROOT%/}/stack0_-_platform/.lock"
[[ -f "${STACK0_LOCK}" ]] || die "Stack0 no esta preparado: falta ${STACK0_LOCK}"

docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1 || \
  die "falta la red ${NETWORK_NAME}; ejecuta primero Stack0"
driver="$(docker network inspect -f '{{.Driver}}' "${NETWORK_NAME}")"
[[ "${driver}" == "bridge" ]] || die "${NETWORK_NAME} usa driver ${driver}, no bridge"

SERVICE_DIR="${BASE_PATH%/}/service_-_litellm"
POSTGRES_DIR="${BASE_PATH%/}/service_-_litellm-postgres"
POSTGRES_SECRET_DIR="${POSTGRES_DIR}/secret"
POSTGRES_ADMIN_PASSWORD_FILE="${POSTGRES_SECRET_DIR}/postgres_admin_password"
CONFIG_SOURCE="${STACK_DIR}/config/litellm/config.yaml"
[[ -f "${CONFIG_SOURCE}" ]] || die "falta ${CONFIG_SOURCE}"

step "Runtime de Stack3"
install -d -m 0750 -o 0 -g 0 "${BASE_PATH}" "${SERVICE_DIR}" "${POSTGRES_DIR}"
install -d -m 0700 -o 0 -g 0 "${POSTGRES_DIR}/data" "${POSTGRES_SECRET_DIR}"
if [[ -e "${POSTGRES_ADMIN_PASSWORD_FILE}" ]]; then
  [[ -f "${POSTGRES_ADMIN_PASSWORD_FILE}" && ! -L "${POSTGRES_ADMIN_PASSWORD_FILE}" && -s "${POSTGRES_ADMIN_PASSWORD_FILE}" ]] || \
    die "estado invalido del secreto PostgreSQL: ${POSTGRES_ADMIN_PASSWORD_FILE}"
  chown 0:0 "${POSTGRES_ADMIN_PASSWORD_FILE}"
  chmod 0600 "${POSTGRES_ADMIN_PASSWORD_FILE}"
  log "secreto administrativo PostgreSQL existente: preservado"
else
  umask 077
  openssl rand -hex 32 >"${POSTGRES_ADMIN_PASSWORD_FILE}"
  chown 0:0 "${POSTGRES_ADMIN_PASSWORD_FILE}"
  chmod 0600 "${POSTGRES_ADMIN_PASSWORD_FILE}"
  log "secreto administrativo PostgreSQL: generado una vez"
fi
log "PostgreSQL dedicado: ${POSTGRES_DIR}/data"

step "Configuracion de LiteLLM"
rm -rf "${SERVICE_DIR}/config"
mkdir -p "${SERVICE_DIR}/config"
install -m 0644 "${CONFIG_SOURCE}" "${SERVICE_DIR}/config/config.yaml"
log "config reescrita desde ${CONFIG_SOURCE}"
log "imagen fijada: ${LITELLM_IMAGE}:${LITELLM_VERSION}"

step "Validacion de Docker Compose"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" config --quiet
log "compose valido"

{
  printf 'stack=%s\n' "${STACK_NAME}"
  printf 'prepared_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "${LOCK_FILE}"

step "Preparacion terminada"
log "lock creado: ${LOCK_FILE}"
log "PostgreSQL pertenece ahora a Stack3"
