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
for key in STACKS_ROOT BASE_PATH NETWORK_NAME SEARXNG_SECRET SEARXNG_BASE_URL REDIS_PASSWORD \
           RABBITMQ_USER RABBITMQ_PASSWORD FIRECRAWL_DB_USER FIRECRAWL_DB_PASSWORD FIRECRAWL_DB_NAME; do
  require_env "${key}"
done

[[ "${STACKS_ROOT}" = /* && "${BASE_PATH}" = /* ]] || die "STACKS_ROOT y BASE_PATH deben ser rutas absolutas"
[[ "${STACK_DIR}" == "${STACKS_ROOT%/}/${STACK_NAME}" ]] || \
  die "este stack debe residir en ${STACKS_ROOT%/}/${STACK_NAME}; ruta actual: ${STACK_DIR}"
[[ "${STACKS_ROOT%/}" != "${BASE_PATH%/}" ]] || die "STACKS_ROOT y BASE_PATH deben ser distintos"
[[ "${SEARXNG_BASE_URL}" == https://* ]] || die "SEARXNG_BASE_URL debe ser HTTPS"
[[ "${FIRECRAWL_DB_USER}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "FIRECRAWL_DB_USER no es valido"
[[ "${FIRECRAWL_DB_USER}" != "postgres" ]] || die "FIRECRAWL_DB_USER no puede ser postgres"
[[ "${FIRECRAWL_DB_NAME}" == "postgres" ]] || die "FIRECRAWL_DB_NAME debe ser postgres para NUQ/pg_cron"

STACK0_LOCK="${STACKS_ROOT%/}/stack0_-_platform/.lock"
SETTINGS_SOURCE="${STACK_DIR}/config/searxng/settings.yml"
LIMITER_SOURCE="${STACK_DIR}/config/searxng/limiter.toml"
POSTGRES_INIT_SOURCE="${STACK_DIR}/config/postgres/020-firecrawl-app-role.sh"
SEARXNG_SERVICE="${BASE_PATH%/}/service_-_searxng"
SEARXNG_CONFIG="${SEARXNG_SERVICE}/config"
SEARXNG_DATA="${SEARXNG_SERVICE}/data"
POSTGRES_SERVICE="${BASE_PATH%/}/service_-_firecrawl-postgres"
POSTGRES_DATA="${POSTGRES_SERVICE}/data"
POSTGRES_SECRET_DIR="${POSTGRES_SERVICE}/secret"
POSTGRES_ADMIN_PASSWORD_FILE="${POSTGRES_SECRET_DIR}/postgres_admin_password"

[[ -f "${STACK0_LOCK}" ]] || die "falta ${STACK0_LOCK}; prepara primero Stack0"
[[ -f "${SETTINGS_SOURCE}" ]] || die "falta ${SETTINGS_SOURCE}"
[[ -f "${LIMITER_SOURCE}" ]] || die "falta ${LIMITER_SOURCE}"
[[ -f "${POSTGRES_INIT_SOURCE}" ]] || die "falta ${POSTGRES_INIT_SOURCE}"

mkdir -p "${BASE_PATH}"

write_lock() {
  umask 022
  {
    printf 'stack=%s\n' "${STACK_NAME}"
    printf 'prepared_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } > "${LOCK_FILE}"
}

step "Red Docker compartida ${NETWORK_NAME}"
docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1 || \
  die "falta ${NETWORK_NAME}; instala/prepara primero Stack0"
driver="$(docker network inspect -f '{{.Driver}}' "${NETWORK_NAME}")"
[[ "${driver}" == "bridge" ]] || die "${NETWORK_NAME} usa driver ${driver}, no bridge"
log "existe, es bridge y permanece propiedad de Stack0"

step "Directorios persistentes"
for directory in \
  "${SEARXNG_SERVICE}" \
  "${SEARXNG_CONFIG}" \
  "${SEARXNG_DATA}" \
  "${BASE_PATH}/service_-_firecrawl-redis/data" \
  "${BASE_PATH}/service_-_firecrawl-rabbitmq/data" \
  "${POSTGRES_SERVICE}"; do
  [[ ! -L "${directory}" ]] || die "directorio runtime no puede ser un symlink: ${directory}"
  [[ ! -e "${directory}" || -d "${directory}" ]] || die "ruta runtime no es un directorio: ${directory}"
done

mkdir -p \
  "${SEARXNG_CONFIG}" \
  "${SEARXNG_DATA}" \
  "${BASE_PATH}/service_-_firecrawl-redis/data" \
  "${BASE_PATH}/service_-_firecrawl-rabbitmq/data" \
  "${POSTGRES_SERVICE}"

# PGDATA belongs to the PostgreSQL container. Existing ownership/mode are never
# rewritten by PREPARE. A new empty directory is created and the official
# PostgreSQL entrypoint will establish its runtime ownership during initdb.
if [[ -e "${POSTGRES_DATA}" || -L "${POSTGRES_DATA}" ]]; then
  [[ -d "${POSTGRES_DATA}" && ! -L "${POSTGRES_DATA}" ]] || \
    die "PGDATA invalido: ${POSTGRES_DATA} debe ser un directorio real"
  log "PGDATA existente: ownership y permisos preservados"
else
  install -d -m 0700 "${POSTGRES_DATA}"
  log "PGDATA vacio creado; PostgreSQL ajustara ownership durante initdb"
fi
log "runtime preservado: ${BASE_PATH}"

step "Secreto administrativo PostgreSQL"
install -d -m 0700 -o 0 -g 0 "${POSTGRES_SECRET_DIR}"
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

step "Configuracion de SearXNG"
for target in \
  "${SEARXNG_CONFIG}/settings.yml" \
  "${SEARXNG_CONFIG}/limiter.toml"; do
  [[ ! -d "${target}" || -L "${target}" ]] || die "ruta de configuracion no puede ser un directorio: ${target}"
done
install -m 0644 "${SETTINGS_SOURCE}" "${SEARXNG_CONFIG}/settings.yml"
install -m 0644 "${LIMITER_SOURCE}" "${SEARXNG_CONFIG}/limiter.toml"
log "directorio bind-mounted preservado; solo se reconcilian ficheros gestionados"

step "Permisos de datos"
image_uid() { docker run --rm --entrypoint id "$1" -u 2>/dev/null || true; }
image_gid() { docker run --rm --entrypoint id "$1" -g 2>/dev/null || true; }
declare -A IMAGE_OF=(
  [searxng]="docker.io/searxng/searxng:2026.9.5-c7f3080aa"
  [firecrawl-redis]="redis:alpine"
  [firecrawl-rabbitmq]="rabbitmq:3-alpine"
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
    chown -R "${uid}:${gid}" "${SEARXNG_CONFIG}" "${SEARXNG_DATA}"
  else
    chown -R "${uid}:${gid}" "${BASE_PATH}/service_-_${svc}/data"
  fi
done
log "PGDATA Firecrawl excluido de reconciliacion de ownership"

step "Validacion de Docker Compose"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" config --quiet
log "compose valido"

write_lock
step "Preparacion terminada"
log "lock creado: ${LOCK_FILE}"
log "postgres queda reservado como rol administrativo; Firecrawl usa ${FIRECRAWL_DB_USER}"
log "red compartida consumida desde Stack0; no se crea ni se modifica"
