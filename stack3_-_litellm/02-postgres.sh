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

command -v docker >/dev/null 2>&1 || die "docker no esta instalado"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 no esta disponible"
[[ -f "${ENV_FILE}" ]] || die "falta ${ENV_FILE}"

grep -Eq '^[A-Za-z_][A-Za-z0-9_]*=.*(<REDACT|\.{5,})' "${ENV_FILE}" && \
  die "${ENV_FILE} contiene valores saneados/incompletos"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

require_env() { local key="$1"; [[ -n "${!key:-}" ]] || die "falta ${key} en ${ENV_FILE}"; }
for key in STACKS_ROOT BASE_PATH POSTGRES_HOST POSTGRES_PORT LITELLM_DB_NAME LITELLM_DB_USER LITELLM_DB_PASSWORD \
           LITELLM_MASTER_KEY LITELLM_SALT_KEY UI_USERNAME UI_PASSWORD STORE_MODEL_IN_DB; do
  require_env "${key}"
done

[[ "${STACK_DIR}" == "${STACKS_ROOT%/}/${STACK_NAME}" ]] || \
  die "este stack debe residir en ${STACKS_ROOT%/}/${STACK_NAME}; ruta actual: ${STACK_DIR}"
[[ "${LITELLM_DB_NAME}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "LITELLM_DB_NAME no es valido"
[[ "${LITELLM_DB_USER}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "LITELLM_DB_USER no es valido"

STACK2_ENV="${STACKS_ROOT%/}/stack2_-_searxng_firecrawl/.env"
[[ -f "${STACK2_ENV}" ]] || die "falta ${STACK2_ENV}; restaura primero el .env operativo de Stack2"

grep -Eq '^[A-Za-z_][A-Za-z0-9_]*=.*(<REDACT|\.{5,})' "${STACK2_ENV}" && \
  die "${STACK2_ENV} contiene valores saneados/incompletos"

read_env_value() {
  local file="$1" key="$2"
  sed -n "s/^${key}=//p" "${file}" | head -n1
}

ADMIN_USER="$(read_env_value "${STACK2_ENV}" POSTGRES_USER)"
ADMIN_PASSWORD="$(read_env_value "${STACK2_ENV}" POSTGRES_PASSWORD)"
ADMIN_DB="$(read_env_value "${STACK2_ENV}" POSTGRES_DB)"
[[ -n "${ADMIN_USER}" ]] || die "POSTGRES_USER no esta definido en ${STACK2_ENV}"
[[ -n "${ADMIN_PASSWORD}" ]] || die "POSTGRES_PASSWORD no esta definido en ${STACK2_ENV}"
[[ -n "${ADMIN_DB}" ]] || die "POSTGRES_DB no esta definido en ${STACK2_ENV}"

step "PostgreSQL de Stack2"
docker inspect "${POSTGRES_HOST}" >/dev/null 2>&1 || die "no existe el contenedor ${POSTGRES_HOST}"
[[ "$(docker inspect -f '{{.State.Running}}' "${POSTGRES_HOST}")" == "true" ]] || \
  die "el contenedor ${POSTGRES_HOST} existe pero no esta arrancado"

for attempt in $(seq 1 30); do
  if docker exec "${POSTGRES_HOST}" pg_isready -h 127.0.0.1 -p "${POSTGRES_PORT}" -U "${ADMIN_USER}" -d "${ADMIN_DB}" >/dev/null 2>&1; then
    break
  fi
  [[ "${attempt}" -lt 30 ]] || die "PostgreSQL no esta disponible"
  sleep 2
done
log "PostgreSQL disponible"

psql_admin() {
  docker exec -i -e PGPASSWORD="${ADMIN_PASSWORD}" "${POSTGRES_HOST}" \
    psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -p "${POSTGRES_PORT}" -U "${ADMIN_USER}" -d "${ADMIN_DB}" "$@"
}

step "Validacion de credenciales administrativas"
printf 'SELECT 1;\n' | psql_admin -tA >/dev/null

step "Usuario PostgreSQL de LiteLLM"
psql_admin -v db_user="${LITELLM_DB_USER}" -v db_password="${LITELLM_DB_PASSWORD}" <<'SQL'
SELECT format('CREATE ROLE %I WITH LOGIN PASSWORD %L', :'db_user', :'db_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'db_user')
\gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'db_user', :'db_password')
\gexec
SQL

step "Base de datos PostgreSQL de LiteLLM"
DB_EXISTS="$(psql_admin -v db_name="${LITELLM_DB_NAME}" -tA <<'SQL'
SELECT 1 FROM pg_database WHERE datname = :'db_name';
SQL
)"
if [[ "${DB_EXISTS}" != "1" ]]; then
  docker exec -e PGPASSWORD="${ADMIN_PASSWORD}" "${POSTGRES_HOST}" \
    createdb -h 127.0.0.1 -p "${POSTGRES_PORT}" -U "${ADMIN_USER}" -O "${LITELLM_DB_USER}" "${LITELLM_DB_NAME}"
fi

psql_admin -v db_name="${LITELLM_DB_NAME}" -v db_user="${LITELLM_DB_USER}" <<'SQL'
SELECT format('ALTER DATABASE %I OWNER TO %I', :'db_name', :'db_user')
\gexec
SQL

docker exec -e PGPASSWORD="${LITELLM_DB_PASSWORD}" "${POSTGRES_HOST}" \
  psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -p "${POSTGRES_PORT}" \
       -U "${LITELLM_DB_USER}" -d "${LITELLM_DB_NAME}" -tAc 'SELECT 1;' >/dev/null

step "Validacion de Docker Compose"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" config --quiet

{
  printf 'stack=%s\n' "${STACK_NAME}"
  printf 'prepared_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "${LOCK_FILE}"

step "Provisionado terminado"
log "lock creado: ${LOCK_FILE}"
