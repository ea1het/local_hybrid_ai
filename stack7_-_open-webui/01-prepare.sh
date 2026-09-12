#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

STACK_NAME="stack7_-_open-webui"
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
command -v docker >/dev/null 2>&1 || die "docker no esta instalado"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 no esta disponible"
[[ -L "${ENV_FILE}" ]] || die "falta el symlink gestionado ${ENV_FILE}"
[[ "$(readlink "${ENV_FILE}")" == "../.env" ]] || die "${ENV_FILE} debe apuntar exactamente a ../.env"
[[ -f "${ENV_FILE}" ]] || die "falta el .env central"
[[ -f "${COMPOSE_FILE}" ]] || die "falta ${COMPOSE_FILE}"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

require_env() { local key="$1"; [[ -n "${!key:-}" ]] || die "falta ${key} en ${ENV_FILE}"; }
for key in STACKS_ROOT BASE_PATH NETWORK_NAME OPENWEBUI_IMAGE OPENWEBUI_VERSION \
           OPENWEBUI_LITELLM_BASE_URL OPENWEBUI_LITELLM_API_KEY OPENWEBUI_SECRET_KEY; do
  require_env "${key}"
done

for key in OPENWEBUI_LITELLM_API_KEY OPENWEBUI_SECRET_KEY; do
  value="${!key}"
  [[ "${value}" != PUT_YOUR_* ]] || die "${key} conserva un placeholder"
done

[[ "${OPENWEBUI_VERSION}" != "latest" && "${OPENWEBUI_VERSION}" != "main" && "${OPENWEBUI_VERSION}" != "dev" ]] || \
  die "OPENWEBUI_VERSION debe ser una version estable fijada, no ${OPENWEBUI_VERSION}"
[[ "${STACKS_ROOT}" = /* && "${BASE_PATH}" = /* ]] || die "STACKS_ROOT y BASE_PATH deben ser rutas absolutas"
[[ "${STACK_DIR}" == "${STACKS_ROOT%/}/${STACK_NAME}" ]] || \
  die "este stack debe residir en ${STACKS_ROOT%/}/${STACK_NAME}; ruta actual: ${STACK_DIR}"
[[ "${STACKS_ROOT%/}" != "${BASE_PATH%/}" ]] || die "STACKS_ROOT y BASE_PATH deben ser distintos"

STACK0_LOCK="${STACKS_ROOT%/}/stack0_-_platform/.lock"
STACK3_LOCK="${STACKS_ROOT%/}/stack3_-_litellm/.lock"
[[ -f "${STACK0_LOCK}" ]] || die "Stack0 no esta preparado: falta ${STACK0_LOCK}"
[[ -f "${STACK3_LOCK}" ]] || die "Stack3 no esta preparado: falta ${STACK3_LOCK}"

step "Red Docker compartida ${NETWORK_NAME}"
docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1 || \
  die "falta ${NETWORK_NAME}; instala/prepara primero Stack0"
driver="$(docker network inspect -f '{{.Driver}}' "${NETWORK_NAME}")"
[[ "${driver}" == "bridge" ]] || die "${NETWORK_NAME} usa driver ${driver}, no bridge"
log "red de Stack0 verificada"

step "Gateway LiteLLM"
if ! docker inspect litellm >/dev/null 2>&1; then
  die "falta el contenedor litellm; despliega primero Stack3"
fi
litellm_running="$(docker inspect -f '{{.State.Running}}' litellm)"
[[ "${litellm_running}" == "true" ]] || die "litellm no esta en ejecucion"
log "LiteLLM disponible"

step "Runtime persistente Open WebUI"
DATA_DIR="${BASE_PATH%/}/service_-_open-webui/data"
[[ ! -L "${BASE_PATH%/}/service_-_open-webui" ]] || die "runtime Open WebUI no puede ser symlink"
[[ ! -e "${BASE_PATH%/}/service_-_open-webui" || -d "${BASE_PATH%/}/service_-_open-webui" ]] || \
  die "runtime Open WebUI no es un directorio"
mkdir -p "${DATA_DIR}"
chmod 0750 "${BASE_PATH%/}/service_-_open-webui" "${DATA_DIR}"
log "datos persistentes: ${DATA_DIR}"

step "Validacion de Docker Compose"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" config --quiet
log "compose valido"

{
  printf 'stack=%s\n' "${STACK_NAME}"
  printf 'prepared_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >"${LOCK_FILE}"
chmod 0644 "${LOCK_FILE}"

step "Preparacion terminada"
log "lock creado: ${LOCK_FILE}"
log "Open WebUI usara exclusivamente el gateway OpenAI-compatible de Stack3"
