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

[[ "$(id -u)" -eq 0 ]] || die "ejecuta este script como root"
command -v docker >/dev/null 2>&1 || die "docker no esta instalado"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 no esta disponible"
[[ -f "${ENV_FILE}" ]] || die "falta ${ENV_FILE}"
[[ -f "${LOCK_FILE}" ]] || die "Stack3 no esta preparado: falta ${LOCK_FILE}; ejecuta primero ./01-prepare.sh"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

for key in BASE_PATH LITELLM_DB_NAME LITELLM_DB_USER LITELLM_DB_PASSWORD; do
  [[ -n "${!key:-}" ]] || die "falta ${key} en ${ENV_FILE}"
done

compose=(docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}")

step "Arranque de PostgreSQL dedicado"
"${compose[@]}" up -d litellm-postgres

for attempt in $(seq 1 40); do
  if docker exec litellm-postgres pg_isready -U "${LITELLM_DB_USER}" -d "${LITELLM_DB_NAME}" >/dev/null 2>&1; then
    break
  fi
  [[ "${attempt}" -lt 40 ]] || die "litellm-postgres no esta disponible"
  sleep 2
done
log "litellm-postgres disponible"

step "Validacion de credenciales"
docker exec -e PGPASSWORD="${LITELLM_DB_PASSWORD}" litellm-postgres \
  psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -U "${LITELLM_DB_USER}" \
       -d "${LITELLM_DB_NAME}" -tAc 'SELECT 1;' >/dev/null
log "conexion PostgreSQL: OK"

step "Validacion de Docker Compose"
"${compose[@]}" config --quiet
log "compose valido"

step "Provisionado terminado"
log "PostgreSQL dedicado de Stack3 provisionado y validado"
