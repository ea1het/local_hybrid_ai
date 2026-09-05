#!/usr/bin/env bash
set -Eeuo pipefail

STACK_NAME="stack1_-_haproxy_web"
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
for key in STACKS_ROOT RUNTIME_ROOT HAPROXY_HTTP_PORT HAPROXY_HTTPS_PORT ROOT_HOSTNAME \
           WEB_TARGET SEARCH_HOSTNAME SEARCH_TARGET CHAT_HOSTNAME CHAT_TARGET \
           GIT_HOSTNAME GIT_TARGET; do
  require_env "${key}"
done

[[ "${STACKS_ROOT}" = /* && "${RUNTIME_ROOT}" = /* ]] || die "STACKS_ROOT y RUNTIME_ROOT deben ser rutas absolutas"
[[ "${STACK_DIR}" == "${STACKS_ROOT%/}/${STACK_NAME}" ]] || \
  die "este stack debe residir en ${STACKS_ROOT%/}/${STACK_NAME}; ruta actual: ${STACK_DIR}"
[[ "${STACKS_ROOT%/}" != "${RUNTIME_ROOT%/}" ]] || die "STACKS_ROOT y RUNTIME_ROOT deben ser distintos"

NETWORK_NAME="redlocal"
HAPROXY_SERVICE="${RUNTIME_ROOT%/}/service_-_haproxy"
WEB_SERVICE="${RUNTIME_ROOT%/}/service_-_web"
HAPROXY_SOURCE="${STACK_DIR}/config/haproxy"
WEB_SOURCE="${STACK_DIR}/config/web"

for file in haproxy.cfg casa.lan.crt casa.lan.key minimal.cnf; do
  [[ -s "${HAPROXY_SOURCE}/${file}" ]] || die "falta o esta vacio ${HAPROXY_SOURCE}/${file}"
done
[[ -f "${WEB_SOURCE}/index.html" ]] || die "falta ${WEB_SOURCE}/index.html"

mkdir -p "${RUNTIME_ROOT}"

write_lock() {
  umask 022
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

step "Configuracion de HAProxy"
mkdir -p "${HAPROXY_SERVICE}"
rm -rf "${HAPROXY_SERVICE}/config"
mkdir -p "${HAPROXY_SERVICE}/config"
cp -a "${HAPROXY_SOURCE}/." "${HAPROXY_SERVICE}/config/"
chmod 0644 "${HAPROXY_SERVICE}/config/haproxy.cfg" "${HAPROXY_SERVICE}/config/casa.lan.crt" "${HAPROXY_SERVICE}/config/minimal.cnf"
[[ -f "${HAPROXY_SERVICE}/config/generate.txt" ]] && chmod 0644 "${HAPROXY_SERVICE}/config/generate.txt"
chmod 0640 "${HAPROXY_SERVICE}/config/casa.lan.key"

step "Contenido web"
rm -rf "${WEB_SERVICE}"
mkdir -p "${WEB_SERVICE}"
cp -a "${WEB_SOURCE}/." "${WEB_SERVICE}/"
chmod 0644 "${WEB_SERVICE}/index.html"

step "Validacion de HAProxy"
docker run --rm \
  -v "${HAPROXY_SERVICE}/config:/usr/local/etc/haproxy:ro" \
  -e ROOT_HOSTNAME="${ROOT_HOSTNAME}" \
  -e WEB_TARGET="${WEB_TARGET}" \
  -e SEARCH_HOSTNAME="${SEARCH_HOSTNAME}" \
  -e SEARCH_TARGET="${SEARCH_TARGET}" \
  -e CHAT_HOSTNAME="${CHAT_HOSTNAME}" \
  -e CHAT_TARGET="${CHAT_TARGET}" \
  -e GIT_HOSTNAME="${GIT_HOSTNAME}" \
  -e GIT_TARGET="${GIT_TARGET}" \
  haproxy:3.0-alpine haproxy -c -f /usr/local/etc/haproxy/haproxy.cfg >/dev/null
log "haproxy.cfg valida"

step "Validacion de Docker Compose"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" config --quiet
log "compose valido"

write_lock
step "Preparacion terminada"
log "lock creado: ${LOCK_FILE}"
