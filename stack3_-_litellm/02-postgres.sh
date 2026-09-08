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

POSTGRES_SECRET_FILE="${BASE_PATH%/}/service_-_litellm-postgres/secret/postgres_admin_password"
[[ -f "${POSTGRES_SECRET_FILE}" && ! -L "${POSTGRES_SECRET_FILE}" && -s "${POSTGRES_SECRET_FILE}" ]] || \
  die "falta el secreto administrativo PostgreSQL; ejecuta primero ./01-prepare.sh"
POSTGRES_ADMIN_PASSWORD="$(<"${POSTGRES_SECRET_FILE}")"
[[ -n "${POSTGRES_ADMIN_PASSWORD}" ]] || die "el secreto administrativo PostgreSQL esta vacio"

compose=(docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}")

step "Arranque de PostgreSQL dedicado"
"${compose[@]}" up -d litellm-postgres

for attempt in $(seq 1 40); do
  if docker exec litellm-postgres pg_isready -U postgres -d postgres >/dev/null 2>&1; then
    break
  fi
  [[ "${attempt}" -lt 40 ]] || die "litellm-postgres no esta disponible"
  sleep 2
done
log "litellm-postgres disponible"

psql_admin() {
  docker exec -i -e PGPASSWORD="${POSTGRES_ADMIN_PASSWORD}" litellm-postgres \
    psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -U postgres -d postgres "$@"
}

step "Usuario PostgreSQL de LiteLLM"
psql_admin -v db_user="${LITELLM_DB_USER}" -v db_password="${LITELLM_DB_PASSWORD}" <<'SQL'
SELECT format('CREATE ROLE %I WITH LOGIN PASSWORD %L', :'db_user', :'db_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'db_user')
\gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION', :'db_user', :'db_password')
\gexec
SQL

step "Base de datos PostgreSQL de LiteLLM"
DB_EXISTS="$(psql_admin -v db_name="${LITELLM_DB_NAME}" -tA <<'SQL'
SELECT 1 FROM pg_database WHERE datname = :'db_name';
SQL
)"
if [[ "${DB_EXISTS}" != "1" ]]; then
  docker exec -e PGPASSWORD="${POSTGRES_ADMIN_PASSWORD}" litellm-postgres \
    createdb -h 127.0.0.1 -U postgres -O "${LITELLM_DB_USER}" "${LITELLM_DB_NAME}"
fi

psql_admin -v db_name="${LITELLM_DB_NAME}" -v db_user="${LITELLM_DB_USER}" <<'SQL'
SELECT format('ALTER DATABASE %I OWNER TO %I', :'db_name', :'db_user')
\gexec
SQL

step "Validacion de credenciales LiteLLM"
docker exec -e PGPASSWORD="${LITELLM_DB_PASSWORD}" litellm-postgres \
  psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -U "${LITELLM_DB_USER}" \
       -d "${LITELLM_DB_NAME}" -tAc 'SELECT 1;' >/dev/null
log "conexion PostgreSQL: OK"

step "Validacion de Docker Compose"
"${compose[@]}" config --quiet
log "compose valido"

step "Provisionado terminado"
log "PostgreSQL dedicado de Stack3 provisionado y validado"
