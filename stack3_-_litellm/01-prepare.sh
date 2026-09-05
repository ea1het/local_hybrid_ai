#!/usr/bin/env bash
set -Eeuo pipefail

STACK_NAME="stack3_-_litellm"
STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
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
command -v docker >/dev/null 2>&1 || die "docker no esta instalado"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 no esta disponible"
[[ -f "${ENV_FILE}" ]] || die "falta ${ENV_FILE}"
[[ -f "${COMPOSE_FILE}" ]] || die "falta ${COMPOSE_FILE}"

grep -Eq '^[A-Za-z_][A-Za-z0-9_]*=.*(<REDACT|\.{5,})' "${ENV_FILE}" && \
  die "${ENV_FILE} contiene valores saneados/incompletos; restaura los valores operativos antes de ejecutar el script"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

require_env() { local key="$1"; [[ -n "${!key:-}" ]] || die "falta ${key} en ${ENV_FILE}"; }
for key in BASE_PATH LITELLM_IMAGE LITELLM_VERSION LITELLM_MASTER_KEY LITELLM_SALT_KEY UI_USERNAME UI_PASSWORD \
           STORE_MODEL_IN_DB POSTGRES_HOST POSTGRES_PORT LITELLM_DB_NAME \
           LITELLM_DB_USER LITELLM_DB_PASSWORD; do
  require_env "${key}"
done

[[ "${BASE_PATH}" = /* ]] || die "BASE_PATH debe ser una ruta absoluta"
[[ "${STACK_DIR}" == "${BASE_PATH}/${STACK_NAME}" ]] || \
  die "este stack debe residir en ${BASE_PATH}/${STACK_NAME}; ruta actual: ${STACK_DIR}"
[[ "${LITELLM_IMAGE}" != *:latest ]] || die "LITELLM_IMAGE no debe usar :latest"
[[ "${LITELLM_VERSION}" != "latest" ]] || die "LITELLM_VERSION no puede ser latest"

NETWORK_NAME="redlocal"
SERVICE_DIR="${BASE_PATH}/service_-_litellm"
CONFIG_SOURCE="${STACK_DIR}/config/litellm/config.yaml"
[[ -f "${CONFIG_SOURCE}" ]] || die "falta ${CONFIG_SOURCE}"

step "Migracion de ruta antigua"
if [[ -e "${BASE_PATH}/litellm" && -e "${SERVICE_DIR}" ]]; then
  die "existen simultaneamente ${BASE_PATH}/litellm y ${SERVICE_DIR}; resuelve manualmente la migracion"
elif [[ -e "${BASE_PATH}/litellm" ]]; then
  mv "${BASE_PATH}/litellm" "${SERVICE_DIR}"
  log "migrado ${BASE_PATH}/litellm -> ${SERVICE_DIR}"
fi

step "Red Docker ${NETWORK_NAME}"
if docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
  driver="$(docker network inspect -f '{{.Driver}}' "${NETWORK_NAME}")"
  [[ "${driver}" == "bridge" ]] || die "${NETWORK_NAME} existe pero usa driver ${driver}, no bridge"
  log "existe y es bridge"
else
  docker network create --driver bridge "${NETWORK_NAME}" >/dev/null
  log "creada"
fi

step "Configuracion de LiteLLM"
mkdir -p "${SERVICE_DIR}"
rm -rf "${SERVICE_DIR}/config"
mkdir -p "${SERVICE_DIR}/config"
install -m 0644 "${CONFIG_SOURCE}" "${SERVICE_DIR}/config/config.yaml"
log "config reescrita desde ${CONFIG_SOURCE}"
log "imagen fijada: ${LITELLM_IMAGE}:${LITELLM_VERSION}"

step "Validacion de Docker Compose"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" config --quiet
log "compose valido"

step "Paso 1 terminado"
log "PostgreSQL aun debe provisionarse con ./02-postgres.sh"
