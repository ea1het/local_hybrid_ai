#!/usr/bin/env bash
set -Eeuo pipefail

STACK_NAME="stack2_-_searxng_firecrawl"
STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="${STACK_DIR}/.env"

log()  { printf '  %s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "ejecuta este script como root"
for cmd in docker install cmp; do
  command -v "${cmd}" >/dev/null 2>&1 || die "${cmd} no esta instalado"
done
[[ -f "${ENV_FILE}" ]] || die "falta ${ENV_FILE}"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

require_env() { local key="$1"; [[ -n "${!key:-}" ]] || die "falta ${key} en ${ENV_FILE}"; }
for key in BASE_PATH POSTGRES_PASSWORD FIRECRAWL_DB_USER FIRECRAWL_DB_PASSWORD FIRECRAWL_DB_NAME; do
  require_env "${key}"
done

[[ "${FIRECRAWL_DB_USER}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "FIRECRAWL_DB_USER no es valido"
[[ "${FIRECRAWL_DB_NAME}" == "postgres" ]] || die "FIRECRAWL_DB_NAME debe ser postgres para NUQ/pg_cron"
[[ "${FIRECRAWL_DB_USER}" != "postgres" ]] || die "FIRECRAWL_DB_USER no puede ser postgres"

docker inspect firecrawl-postgres >/dev/null 2>&1 || die "no existe el contenedor firecrawl-postgres"
[[ "$(docker inspect -f '{{.State.Running}}' firecrawl-postgres)" == "true" ]] || die "firecrawl-postgres no esta running"

SECRET_DIR="${BASE_PATH%/}/service_-_firecrawl-postgres/secret"
ADMIN_SECRET="${SECRET_DIR}/postgres_admin_password"

step "Adopcion del secreto administrativo existente"
install -d -m 0700 -o 0 -g 0 "${SECRET_DIR}"
if [[ -e "${ADMIN_SECRET}" ]]; then
  [[ -f "${ADMIN_SECRET}" && ! -L "${ADMIN_SECRET}" && -s "${ADMIN_SECRET}" ]] || \
    die "estado invalido del secreto administrativo: ${ADMIN_SECRET}"
  if ! printf '%s\n' "${POSTGRES_PASSWORD}" | cmp -s - "${ADMIN_SECRET}"; then
    die "el secreto runtime existente no coincide con POSTGRES_PASSWORD; no se modifica"
  fi
  chown 0:0 "${ADMIN_SECRET}"
  chmod 0600 "${ADMIN_SECRET}"
  log "secreto administrativo existente y coherente: preservado"
else
  umask 077
  printf '%s\n' "${POSTGRES_PASSWORD}" >"${ADMIN_SECRET}"
  chown 0:0 "${ADMIN_SECRET}"
  chmod 0600 "${ADMIN_SECRET}"
  log "POSTGRES_PASSWORD actual adoptado una vez como secreto runtime"
fi

step "Creacion/reconciliacion del rol aplicativo Firecrawl"
docker exec -i \
  -e FC_APP_USER="${FIRECRAWL_DB_USER}" \
  -e FC_APP_PASSWORD="${FIRECRAWL_DB_PASSWORD}" \
  firecrawl-postgres \
  psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'EOSQL'
\getenv app_user FC_APP_USER
\getenv app_password FC_APP_PASSWORD

SELECT format(
  'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
  :'app_user', :'app_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')
\gexec

SELECT format(
  'ALTER ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
  :'app_user', :'app_password'
)
\gexec

SELECT format('GRANT CONNECT ON DATABASE postgres TO %I', :'app_user')
\gexec
SELECT format('GRANT USAGE ON SCHEMA nuq TO %I', :'app_user')
\gexec
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA nuq TO %I', :'app_user')
\gexec
SELECT format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA nuq TO %I', :'app_user')
\gexec

SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA nuq GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
  :'app_user'
)
\gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA nuq GRANT USAGE, SELECT ON SEQUENCES TO %I',
  :'app_user'
)
\gexec
EOSQL

step "Validacion de privilegios del rol"
ROLE_BAD="$(docker exec -i -e FC_APP_USER="${FIRECRAWL_DB_USER}" firecrawl-postgres psql -U postgres -d postgres -v ON_ERROR_STOP=1 -At <<'EOSQL'
\getenv app_user FC_APP_USER
SELECT CASE
  WHEN rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls OR NOT rolcanlogin
  THEN 1 ELSE 0 END
FROM pg_roles
WHERE rolname = :'app_user';
EOSQL
)"
[[ "${ROLE_BAD}" == "0" ]] || die "rol aplicativo ausente o con privilegios administrativos inesperados"
log "rol aplicativo sin privilegios administrativos"

step "Prueba TCP y CRUD transaccional como rol aplicativo"
docker exec -i \
  -e PGPASSWORD="${FIRECRAWL_DB_PASSWORD}" \
  firecrawl-postgres \
  psql -h 127.0.0.1 -U "${FIRECRAWL_DB_USER}" -d postgres -v ON_ERROR_STOP=1 <<'EOSQL'
BEGIN;
SELECT count(*) >= 0 AS can_select FROM nuq.queue_scrape;
INSERT INTO nuq.queue_scrape(data) VALUES ('{"migration_probe":true}'::jsonb) RETURNING id \gset
UPDATE nuq.queue_scrape SET data='{"migration_probe":"updated"}'::jsonb WHERE id=:'id';
DELETE FROM nuq.queue_scrape WHERE id=:'id';
ROLLBACK;
EOSQL
log "autenticacion TCP y SELECT/INSERT/UPDATE/DELETE: OK (ROLLBACK aplicado)"

step "Migracion preparada"
log "postgres sigue siendo admin/owner"
log "${FIRECRAWL_DB_USER} queda preparado como rol aplicativo de minimo privilegio"
log "no se ha reiniciado ni recreado ningun contenedor"
log "no se ha modificado PGDATA"
log "siguiente paso: aplicar el Compose nuevo y validar Firecrawl"
