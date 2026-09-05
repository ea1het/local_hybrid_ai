#!/usr/bin/env bash
set -Eeuo pipefail

STACK_NAME="stack2_-_searxng_firecrawl"
STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${STACK_DIR}/.env"
COMPOSE_FILE="${STACK_DIR}/docker-compose.yml"
LOCK_FILE="${STACK_DIR}/.lock"

log()  { printf '  %s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
warn() { printf '  AVISO: %s\n' "$*" >&2; }
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
  die "${ENV_FILE} contiene valores saneados/incompletos"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

require_env() { local key="$1"; [[ -n "${!key:-}" ]] || die "falta ${key} en ${ENV_FILE}"; }
for key in STACKS_ROOT BASE_PATH SEARXNG_SECRET SEARXNG_BASE_URL REDIS_PASSWORD \
           RABBITMQ_USER RABBITMQ_PASSWORD POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB; do
  require_env "${key}"
done

[[ "${STACKS_ROOT}" = /* && "${BASE_PATH}" = /* ]] || die "STACKS_ROOT y BASE_PATH deben ser rutas absolutas"
[[ "${STACK_DIR}" == "${STACKS_ROOT%/}/${STACK_NAME}" ]] || \
  die "este stack debe residir en ${STACKS_ROOT%/}/${STACK_NAME}; ruta actual: ${STACK_DIR}"
[[ "${STACKS_ROOT%/}" != "${BASE_PATH%/}" ]] || die "STACKS_ROOT y BASE_PATH deben ser distintos"
[[ "${SEARXNG_BASE_URL}" == https://* ]] || die "SEARXNG_BASE_URL debe ser HTTPS"

NETWORK_NAME="redlocal"
SETTINGS_SOURCE="${STACK_DIR}/config/searxng/settings.yml"
LIMITER_SOURCE="${STACK_DIR}/config/searxng/limiter.toml"
[[ -f "${SETTINGS_SOURCE}" ]] || die "falta ${SETTINGS_SOURCE}"
[[ -f "${LIMITER_SOURCE}" ]] || die "falta ${LIMITER_SOURCE}"

mkdir -p "${BASE_PATH}"

write_lock() {
  {
    printf 'stack=%s\n' "${STACK_NAME}"
    printf 'prepared_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } > "${LOCK_FILE}"
}

step "Red Docker ${NETWORK_NAME}"
if docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
  driver="$(docker network inspect -f '{{.Driver}}' "${NETWORK_NAME}")"
  [[ "${driver}" == "bridge" ]] || die "${NETWORK_NAME} existe pero usa driver ${driver}, no bridge"
  log "existe y es bridge"
else
  docker network create --driver bridge "${NETWORK_NAME}" >/dev/null
  log "creada"
fi

step "Directorios persistentes"
mkdir -p \
  "${BASE_PATH}/service_-_searxng/config" \
  "${BASE_PATH}/service_-_searxng/data" \
  "${BASE_PATH}/service_-_firecrawl-redis/data" \
  "${BASE_PATH}/service_-_firecrawl-rabbitmq/data" \
  "${BASE_PATH}/service_-_firecrawl-postgres/data"
log "runtime: ${BASE_PATH}"

step "Configuracion de SearXNG"
rm -rf "${BASE_PATH}/service_-_searxng/config"
mkdir -p "${BASE_PATH}/service_-_searxng/config"
install -m 0644 "${SETTINGS_SOURCE}" "${BASE_PATH}/service_-_searxng/config/settings.yml"
install -m 0644 "${LIMITER_SOURCE}" "${BASE_PATH}/service_-_searxng/config/limiter.toml"

step "Permisos de datos"
image_uid() { docker run --rm --entrypoint id "$1" -u 2>/dev/null || true; }
image_gid() { docker run --rm --entrypoint id "$1" -g 2>/dev/null || true; }
declare -A IMAGE_OF=(
  [searxng]="docker.io/searxng/searxng:latest"
  [firecrawl-redis]="redis:alpine"
  [firecrawl-rabbitmq]="rabbitmq:3-alpine"
  [firecrawl-postgres]="ghcr.io/firecrawl/nuq-postgres:latest"
)
for svc in "${!IMAGE_OF[@]}"; do
  uid="$(image_uid "${IMAGE_OF[$svc]}")"
  gid="$(image_gid "${IMAGE_OF[$svc]}")"
  if [[ -z "${uid}" || -z "${gid}" ]]; then
    warn "${svc}: no se pudo determinar UID/GID; se conserva propietario"
    continue
  fi
  [[ "${uid}" == "0" ]] && continue
  if [[ "${svc}" == "searxng" ]]; then
    chown -R "${uid}:${gid}" "${BASE_PATH}/service_-_searxng/config" "${BASE_PATH}/service_-_searxng/data"
  else
    chown -R "${uid}:${gid}" "${BASE_PATH}/service_-_${svc}/data"
  fi
done

step "Validacion de Docker Compose"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" config --quiet
log "compose valido"

write_lock
step "Preparacion terminada"
log "lock creado: ${LOCK_FILE}"
