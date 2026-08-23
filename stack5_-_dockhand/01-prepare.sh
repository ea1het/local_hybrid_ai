#!/usr/bin/env bash
set -Eeuo pipefail

STACK_NAME="stack5_-_dockhand"
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

command -v docker >/dev/null 2>&1 || die "docker no esta instalado"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 no esta disponible"
[[ -f "${ENV_FILE}" ]] || die "falta ${ENV_FILE}"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

[[ -n "${BASE_PATH:-}" ]] || die "falta BASE_PATH en ${ENV_FILE}"
[[ "${BASE_PATH}" = /* ]] || die "BASE_PATH debe ser una ruta absoluta"
[[ "${STACK_DIR}" == "${BASE_PATH}/${STACK_NAME}" ]] || \
  die "este stack debe residir en ${BASE_PATH}/${STACK_NAME}; ruta actual: ${STACK_DIR}"

step "Red Docker redlocal"
if docker network inspect redlocal >/dev/null 2>&1; then
  driver="$(docker network inspect -f '{{.Driver}}' redlocal)"
  [[ "${driver}" == "bridge" ]] || die "redlocal existe pero usa driver ${driver}, no bridge"
  log "existe y es bridge"
else
  docker network create --driver bridge redlocal >/dev/null
  log "creada"
fi

step "Volumen externo dockhand_data"
docker volume inspect dockhand_data >/dev/null 2>&1 || \
  die "el volumen externo dockhand_data no existe; este stack no lo crea automaticamente"
log "existe"

step "Validacion de Docker Compose"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" config --quiet
log "compose valido"

{
  printf 'stack=%s\n' "${STACK_NAME}"
  printf 'prepared_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "${LOCK_FILE}"

step "Preparacion terminada"
log "lock creado: ${LOCK_FILE}"
log "arranque: docker compose --env-file ${ENV_FILE} -f ${COMPOSE_FILE} up -d"
