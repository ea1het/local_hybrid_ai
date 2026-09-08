#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="${STACK_DIR}/.env"
COMPOSE_FILE="${STACK_DIR}/docker-compose.yml"
LOCK_FILE="${STACK_DIR}/.lock"
SOURCE_CONTAINER="firecrawl-postgres"
TARGET_CONTAINER="litellm-postgres"
LITELLM_CONTAINER="litellm"

log()  { printf '  %s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "ejecuta este script como root"
for cmd in docker cmp mktemp date install; do
  command -v "${cmd}" >/dev/null 2>&1 || die "falta el comando requerido: ${cmd}"
done
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 no esta disponible"
[[ -f "${ENV_FILE}" ]] || die "falta ${ENV_FILE}"
[[ -f "${LOCK_FILE}" ]] || die "Stack3 no esta preparado; ejecuta primero ./01-prepare.sh"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

for key in BASE_PATH LITELLM_DB_NAME LITELLM_DB_USER LITELLM_DB_PASSWORD; do
  [[ -n "${!key:-}" ]] || die "falta ${key} en ${ENV_FILE}"
done

compose=(docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}")

for container in "${SOURCE_CONTAINER}" "${LITELLM_CONTAINER}"; do
  docker inspect "${container}" >/dev/null 2>&1 || die "no existe el contenedor ${container}"
  [[ "$(docker inspect -f '{{.State.Running}}' "${container}")" == "true" ]] || die "${container} no esta arrancado"
done

# Confirm that the currently deployed LiteLLM still points at the legacy DB.
if ! docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "${LITELLM_CONTAINER}" \
     | grep '^DATABASE_URL=' | grep -q '@firecrawl-postgres:'; then
  die "LiteLLM no apunta a firecrawl-postgres; no hay una migracion legacy segura que ejecutar"
fi

step "PostgreSQL destino de Stack3"
"${compose[@]}" up -d "${TARGET_CONTAINER}"
for attempt in $(seq 1 40); do
  if docker exec "${TARGET_CONTAINER}" pg_isready -U "${LITELLM_DB_USER}" -d "${LITELLM_DB_NAME}" >/dev/null 2>&1; then
    break
  fi
  [[ "${attempt}" -lt 40 ]] || die "${TARGET_CONTAINER} no esta disponible"
  sleep 2
done

TARGET_TABLES="$(docker exec -e PGPASSWORD="${LITELLM_DB_PASSWORD}" "${TARGET_CONTAINER}" \
  psql -At -h 127.0.0.1 -U "${LITELLM_DB_USER}" -d "${LITELLM_DB_NAME}" \
  -c "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema');")"
[[ "${TARGET_TABLES}" == "0" ]] || die "la base destino no esta vacia (${TARGET_TABLES} tablas); no se sobrescribe"

BACKUP_ROOT="/root/litellm-postgres-migration-$(date +%Y%m%d-%H%M%S)"
install -d -m 0700 "${BACKUP_ROOT}"
DUMP_FILE="${BACKUP_ROOT}/litellm.dump"
SOURCE_TABLES_FILE="${BACKUP_ROOT}/source-tables.txt"
TARGET_TABLES_FILE="${BACKUP_ROOT}/target-tables.txt"

step "Congelacion de escrituras"
docker stop "${LITELLM_CONTAINER}" >/dev/null
log "LiteLLM detenido; el contenedor legacy se conserva para rollback"

rollback_legacy() {
  rc=$?
  trap - ERR
  printf '\nERROR: fallo durante la migracion; intentando rollback a PostgreSQL de Stack2\n' >&2
  LITELLM_POSTGRES_HOST=firecrawl-postgres LITELLM_POSTGRES_PORT=5432 \
    "${compose[@]}" up -d --force-recreate litellm >/dev/null 2>&1 || true
  exit "${rc}"
}
trap rollback_legacy ERR

step "Dump consistente de LiteLLM"
docker exec -e PGPASSWORD="${LITELLM_DB_PASSWORD}" "${SOURCE_CONTAINER}" \
  pg_dump -Fc --no-owner --no-privileges \
  -U "${LITELLM_DB_USER}" -d "${LITELLM_DB_NAME}" >"${DUMP_FILE}"
[[ -s "${DUMP_FILE}" ]] || die "el dump resultante esta vacio"
chmod 0600 "${DUMP_FILE}"
log "backup: ${DUMP_FILE}"

step "Restore en PostgreSQL de Stack3"
docker exec -i -e PGPASSWORD="${LITELLM_DB_PASSWORD}" "${TARGET_CONTAINER}" \
  pg_restore --exit-on-error --no-owner --no-privileges \
  -U "${LITELLM_DB_USER}" -d "${LITELLM_DB_NAME}" <"${DUMP_FILE}"

TABLE_QUERY="SELECT schemaname||'.'||tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1;"
docker exec -e PGPASSWORD="${LITELLM_DB_PASSWORD}" "${SOURCE_CONTAINER}" \
  psql -At -U "${LITELLM_DB_USER}" -d "${LITELLM_DB_NAME}" -c "${TABLE_QUERY}" >"${SOURCE_TABLES_FILE}"
docker exec -e PGPASSWORD="${LITELLM_DB_PASSWORD}" "${TARGET_CONTAINER}" \
  psql -At -U "${LITELLM_DB_USER}" -d "${LITELLM_DB_NAME}" -c "${TABLE_QUERY}" >"${TARGET_TABLES_FILE}"
cmp -s "${SOURCE_TABLES_FILE}" "${TARGET_TABLES_FILE}" || die "la lista de tablas origen/destino no coincide"
log "estructura de tablas: OK"

step "Cutover de LiteLLM"
"${compose[@]}" up -d --force-recreate litellm

for attempt in $(seq 1 60); do
  status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${LITELLM_CONTAINER}" 2>/dev/null || true)"
  [[ "${status}" == "healthy" ]] && break
  [[ "${status}" != "unhealthy" ]] || die "LiteLLM quedo unhealthy tras el cutover"
  [[ "${attempt}" -lt 60 ]] || die "LiteLLM no alcanzo estado healthy tras el cutover"
  sleep 2
done

CURRENT_DB_URL="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "${LITELLM_CONTAINER}" | sed -n 's/^DATABASE_URL=//p')"
[[ "${CURRENT_DB_URL}" == *"@litellm-postgres:5432/"* ]] || die "LiteLLM no quedo apuntando a litellm-postgres"

trap - ERR

MARKER="${BASE_PATH%/}/service_-_litellm-postgres/.migration-from-stack2-complete"
printf 'completed_at_utc=%s\nbackup=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${DUMP_FILE}" >"${MARKER}"
chmod 0600 "${MARKER}"

step "Migracion terminada"
log "LiteLLM: healthy sobre litellm-postgres"
log "base legacy en ${SOURCE_CONTAINER}: conservada para rollback"
log "backup: ${DUMP_FILE}"
