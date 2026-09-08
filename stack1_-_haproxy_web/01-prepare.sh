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
for cmd in docker openssl cmp ln; do
  command -v "${cmd}" >/dev/null 2>&1 || die "falta el comando requerido: ${cmd}"
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
for key in STACKS_ROOT BASE_PATH NETWORK_NAME HAPROXY_HTTP_PORT HAPROXY_HTTPS_PORT ROOT_HOSTNAME \
           WEB_TARGET SEARCH_HOSTNAME SEARCH_TARGET CHAT_HOSTNAME CHAT_TARGET \
           GIT_HOSTNAME GIT_TARGET \
           GWIA_HOSTNAME GWIA_TARGET \
           HOMELAB_HOSTNAME HOMELAB_TARGET \
           AGENTIA_HOSTNAME AGENTIA_TARGET; do
  require_env "${key}"
done

PLATFORM_PKI_GID="${PLATFORM_PKI_GID:-1999}"
[[ "${PLATFORM_PKI_GID}" =~ ^[0-9]+$ && "${PLATFORM_PKI_GID}" -gt 0 ]] || \
  die "PLATFORM_PKI_GID debe ser un entero positivo"

[[ "${STACKS_ROOT}" = /* && "${BASE_PATH}" = /* ]] || die "STACKS_ROOT y BASE_PATH deben ser rutas absolutas"
[[ "${STACK_DIR}" == "${STACKS_ROOT%/}/${STACK_NAME}" ]] || \
  die "este stack debe residir en ${STACKS_ROOT%/}/${STACK_NAME}; ruta actual: ${STACK_DIR}"
[[ "${STACKS_ROOT%/}" != "${BASE_PATH%/}" ]] || die "STACKS_ROOT y BASE_PATH deben ser distintos"

HAPROXY_SERVICE="${BASE_PATH%/}/service_-_haproxy"
WEB_SERVICE="${BASE_PATH%/}/service_-_web"
PLATFORM_PKI="${BASE_PATH%/}/service_-_platform/pki"
PLATFORM_CERT="${PLATFORM_PKI}/tls.crt"
PLATFORM_KEY="${PLATFORM_PKI}/tls.key"
HAPROXY_SOURCE="${STACK_DIR}/config/haproxy"
WEB_SOURCE="${STACK_DIR}/config/web"

[[ -s "${HAPROXY_SOURCE}/haproxy.cfg" ]] || die "falta o esta vacio ${HAPROXY_SOURCE}/haproxy.cfg"
[[ -f "${WEB_SOURCE}/index.html" ]] || die "falta ${WEB_SOURCE}/index.html"

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
log "red de Stack0 verificada"

step "PKI central de Stack0"
[[ -s "${PLATFORM_CERT}" ]] || die "falta ${PLATFORM_CERT}; prepara primero la PKI de Stack0"
[[ -s "${PLATFORM_KEY}" ]] || die "falta ${PLATFORM_KEY}; prepara primero la PKI de Stack0"
openssl x509 -in "${PLATFORM_CERT}" -noout >/dev/null 2>&1 || die "certificado de Stack0 invalido"
openssl pkey -in "${PLATFORM_KEY}" -noout >/dev/null 2>&1 || die "clave privada de Stack0 invalida"
cmp -s \
  <(openssl x509 -in "${PLATFORM_CERT}" -pubkey -noout) \
  <(openssl pkey -in "${PLATFORM_KEY}" -pubout) || die "certificado y clave de Stack0 no coinciden"
log "PKI de Stack0 verificada"

step "Configuracion de HAProxy"
mkdir -p "${HAPROXY_SERVICE}"
rm -rf "${HAPROXY_SERVICE}/config"
mkdir -p "${HAPROXY_SERVICE}/config"
install -m 0644 "${HAPROXY_SOURCE}/haproxy.cfg" "${HAPROXY_SERVICE}/config/haproxy.cfg"
ln -s /etc/platform-pki/tls.crt "${HAPROXY_SERVICE}/config/casa.lan.crt"
ln -s /etc/platform-pki/tls.key "${HAPROXY_SERVICE}/config/casa.lan.key"
log "configuracion desplegada; TLS enlazado a Stack0 sin copiar material secreto"

step "Contenido web"
rm -rf "${WEB_SERVICE}"
mkdir -p "${WEB_SERVICE}"
cp -a "${WEB_SOURCE}/." "${WEB_SERVICE}/"
chmod 0644 "${WEB_SERVICE}/index.html"

step "Validacion de HAProxy"
docker run --rm \
  --group-add "${PLATFORM_PKI_GID}" \
  -v "${HAPROXY_SERVICE}/config:/usr/local/etc/haproxy:ro" \
  -v "${PLATFORM_PKI}:/etc/platform-pki:ro" \
  -e ROOT_HOSTNAME="${ROOT_HOSTNAME}" \
  -e WEB_TARGET="${WEB_TARGET}" \
  -e SEARCH_HOSTNAME="${SEARCH_HOSTNAME}" \
  -e SEARCH_TARGET="${SEARCH_TARGET}" \
  -e CHAT_HOSTNAME="${CHAT_HOSTNAME}" \
  -e CHAT_TARGET="${CHAT_TARGET}" \
  -e GIT_HOSTNAME="${GIT_HOSTNAME}" \
  -e GIT_TARGET="${GIT_TARGET}" \
  -e GWIA_HOSTNAME="${GWIA_HOSTNAME}" \
  -e GWIA_TARGET="${GWIA_TARGET}" \
  -e HOMELAB_HOSTNAME="${HOMELAB_HOSTNAME}" \
  -e HOMELAB_TARGET="${HOMELAB_TARGET}" \
  -e AGENTIA_HOSTNAME="${AGENTIA_HOSTNAME}" \
  -e AGENTIA_TARGET="${AGENTIA_TARGET}" \
  haproxy:3.0-alpine haproxy -c -f /usr/local/etc/haproxy/haproxy.cfg >/dev/null
log "haproxy.cfg valida con PKI central"

step "Validacion de Docker Compose"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" config --quiet
log "compose valido"

write_lock
step "Preparacion terminada"
log "lock creado: ${LOCK_FILE}"
log "TLS: consumido directamente desde Stack0"
