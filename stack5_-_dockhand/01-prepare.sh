#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

STACK_NAME="stack5_-_dockhand"
STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="${STACK_DIR}/.env"
COMPOSE_FILE="${STACK_DIR}/docker-compose.yml"
LOCK_FILE="${STACK_DIR}/.lock"
DOCKHAND_VOLUME="dockhand_data"

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

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

for key in STACKS_ROOT BASE_PATH NETWORK_NAME; do
  [[ -n "${!key:-}" ]] || die "falta ${key} en ${ENV_FILE}"
done
[[ "${STACKS_ROOT}" = /* && "${BASE_PATH}" = /* ]] || die "STACKS_ROOT y BASE_PATH deben ser rutas absolutas"
[[ "${STACK_DIR}" == "${STACKS_ROOT%/}/${STACK_NAME}" ]] || \
  die "este stack debe residir en ${STACKS_ROOT%/}/${STACK_NAME}; ruta actual: ${STACK_DIR}"
[[ "${STACKS_ROOT%/}" != "${BASE_PATH%/}" ]] || die "STACKS_ROOT y BASE_PATH deben ser distintos"

STACK0_LOCK="${STACKS_ROOT%/}/stack0_-_platform/.lock"
[[ -f "${STACK0_LOCK}" ]] || die "Stack0 no esta preparado: falta ${STACK0_LOCK}"

step "Red Docker compartida ${NETWORK_NAME}"
docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1 || \
  die "falta ${NETWORK_NAME}; instala/prepara primero Stack0"
driver="$(docker network inspect -f '{{.Driver}}' "${NETWORK_NAME}")"
[[ "${driver}" == "bridge" ]] || die "${NETWORK_NAME} usa driver ${driver}, no bridge"
log "red de Stack0 verificada"

step "Volumen persistente ${DOCKHAND_VOLUME}"
if docker volume inspect "${DOCKHAND_VOLUME}" >/dev/null 2>&1; then
  log "volumen existente preservado"
else
  docker volume create "${DOCKHAND_VOLUME}" >/dev/null
  log "volumen creado"
fi

docker volume inspect "${DOCKHAND_VOLUME}" >/dev/null 2>&1 || \
  die "no se pudo preparar el volumen ${DOCKHAND_VOLUME}"
volume_name="$(docker volume inspect -f '{{.Name}}' "${DOCKHAND_VOLUME}")"
[[ "${volume_name}" == "${DOCKHAND_VOLUME}" ]] || die "volumen inesperado: ${volume_name}"

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
log "volumen ${DOCKHAND_VOLUME}: propiedad de Stack5 y preservado entre despliegues"
