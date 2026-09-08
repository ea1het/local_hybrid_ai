#!/usr/bin/env bash
set -Eeuo pipefail

STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
STACKS_ROOT_DEFAULT="$(cd -- "${STACK_DIR}/.." && pwd -P)"
ENV_FILE="${STACKS_ROOT_DEFAULT}/.env"

log() { printf '  %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "run as root"
for cmd in openssl install mktemp cmp chmod chown rm; do
  command -v "${cmd}" >/dev/null 2>&1 || die "missing required command: ${cmd}"
done
[[ -f "${ENV_FILE}" && ! -L "${ENV_FILE}" ]] || die "missing root operational environment: ${ENV_FILE}"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

[[ -n "${BASE_PATH:-}" ]] || die "BASE_PATH is not defined in ${ENV_FILE}"
[[ -n "${ROOT_HOSTNAME:-}" ]] || die "ROOT_HOSTNAME is not defined in ${ENV_FILE}"
[[ "${BASE_PATH}" == /* ]] || die "BASE_PATH must be absolute"
[[ "${ROOT_HOSTNAME}" =~ ^[A-Za-z0-9.-]+$ ]] || die "ROOT_HOSTNAME contains unsupported characters"

PLATFORM_PKI_GID="${PLATFORM_PKI_GID:-1999}"
[[ "${PLATFORM_PKI_GID}" =~ ^[0-9]+$ && "${PLATFORM_PKI_GID}" -gt 0 ]] || \
  die "PLATFORM_PKI_GID must be a positive integer"

PKI_ROOT="${BASE_PATH%/}/service_-_platform/pki"
CERT_FILE="${PKI_ROOT}/tls.crt"
KEY_FILE="${PKI_ROOT}/tls.key"
CERT_DAYS="${PLATFORM_CERT_DAYS:-3650}"

[[ "${CERT_DAYS}" =~ ^[0-9]+$ && "${CERT_DAYS}" -gt 0 ]] || die "PLATFORM_CERT_DAYS must be a positive integer"
install -d -m 0750 -o 0 -g "${PLATFORM_PKI_GID}" "${PKI_ROOT}"

write_config() {
  local path="$1"
  cat >"${path}" <<EOF
[req]
distinguished_name = dn
x509_extensions = v3_req
prompt = no

[dn]
CN = *.${ROOT_HOSTNAME}

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = *.${ROOT_HOSTNAME}
DNS.2 = ${ROOT_HOSTNAME}
EOF
}

validate_external_pair() {
  local cert="$1" key="$2" tmpdir cert_pub key_pub
  [[ -s "${cert}" && ! -L "${cert}" ]] || die "missing or invalid certificate: ${cert}"
  [[ -s "${key}" && ! -L "${key}" ]] || die "missing or invalid private key: ${key}"
  openssl x509 -in "${cert}" -noout >/dev/null 2>&1 || die "invalid X.509 certificate: ${cert}"
  openssl pkey -in "${key}" -noout >/dev/null 2>&1 || die "invalid private key: ${key}"

  tmpdir="$(mktemp -d "${PKI_ROOT}/.validate.XXXXXX")"
  cert_pub="${tmpdir}/cert.pub"
  key_pub="${tmpdir}/key.pub"
  openssl x509 -in "${cert}" -pubkey -noout >"${cert_pub}"
  openssl pkey -in "${key}" -pubout >"${key_pub}"
  cmp -s "${cert_pub}" "${key_pub}" || { rm -rf "${tmpdir}"; die "certificate and private key do not match"; }
  rm -rf "${tmpdir}"
}

validate_pair() {
  validate_external_pair "${CERT_FILE}" "${KEY_FILE}"
}

normalize_permissions() {
  install -d -m 0750 -o 0 -g "${PLATFORM_PKI_GID}" "${PKI_ROOT}"
  [[ -e "${CERT_FILE}" ]] && { chown 0:"${PLATFORM_PKI_GID}" "${CERT_FILE}"; chmod 0644 "${CERT_FILE}"; }
  [[ -e "${KEY_FILE}" ]] && { chown 0:"${PLATFORM_PKI_GID}" "${KEY_FILE}"; chmod 0640 "${KEY_FILE}"; }
}

install_pair() {
  local cert_source="$1" key_source="$2"
  validate_external_pair "${cert_source}" "${key_source}"
  install -m 0644 -o 0 -g "${PLATFORM_PKI_GID}" "${cert_source}" "${CERT_FILE}"
  install -m 0640 -o 0 -g "${PLATFORM_PKI_GID}" "${key_source}" "${KEY_FILE}"
  validate_pair
  normalize_permissions
}

create_pair() {
  local tmpdir config
  tmpdir="$(mktemp -d "${PKI_ROOT}/.create.XXXXXX")"
  config="${tmpdir}/openssl.cnf"
  write_config "${config}"
  openssl req -x509 -newkey rsa:4096 -sha256 -days "${CERT_DAYS}" -nodes \
    -keyout "${tmpdir}/tls.key" -out "${tmpdir}/tls.crt" -config "${config}" >/dev/null 2>&1
  install_pair "${tmpdir}/tls.crt" "${tmpdir}/tls.key"
  rm -rf "${tmpdir}"
}

renew_cert() {
  [[ -s "${KEY_FILE}" ]] || die "cannot renew without existing private key: ${KEY_FILE}"
  local tmpdir config
  tmpdir="$(mktemp -d "${PKI_ROOT}/.renew.XXXXXX")"
  config="${tmpdir}/openssl.cnf"
  write_config "${config}"
  openssl req -x509 -new -key "${KEY_FILE}" -sha256 -days "${CERT_DAYS}" \
    -out "${tmpdir}/tls.crt" -config "${config}" >/dev/null 2>&1
  install -m 0644 -o 0 -g "${PLATFORM_PKI_GID}" "${tmpdir}/tls.crt" "${CERT_FILE}"
  rm -rf "${tmpdir}"
  validate_pair
  normalize_permissions
}

status() {
  if [[ ! -e "${CERT_FILE}" && ! -e "${KEY_FILE}" ]]; then
    log "PKI state: absent"
    return 1
  fi
  validate_pair
  printf 'PKI root: %s\n' "${PKI_ROOT}"
  openssl x509 -in "${CERT_FILE}" -noout \
    -subject -issuer -dates -fingerprint -sha256 -ext subjectAltName
}

usage() {
  cat <<'EOF'
Usage:
  pki.sh status
  pki.sh create
  pki.sh import CERT KEY
  pki.sh renew
  pki.sh recreate --yes
  pki.sh delete --yes

create    Create a self-signed platform certificate only when no PKI exists.
import    Adopt an existing certificate/key pair only when no platform PKI exists.
renew     Issue a new certificate while preserving the current private key.
recreate  Replace both certificate and private key; explicit confirmation required.
delete    Remove both certificate and private key; explicit confirmation required.
status    Validate the pair and print non-secret certificate metadata.
EOF
}

action="${1:-}"
case "${action}" in
  status)
    status
    ;;
  create)
    if [[ -e "${CERT_FILE}" || -e "${KEY_FILE}" ]]; then
      [[ -s "${CERT_FILE}" && -s "${KEY_FILE}" ]] || die "partial PKI state exists; use recreate --yes after inspection"
      validate_pair
      normalize_permissions
      log "PKI already exists and is valid; preserved"
    else
      create_pair
      log "PKI created for ${ROOT_HOSTNAME}"
    fi
    ;;
  import)
    source_cert="${2:-}"
    source_key="${3:-}"
    [[ -n "${source_cert}" && -n "${source_key}" ]] || die "import requires CERT and KEY paths"
    [[ ! -e "${CERT_FILE}" && ! -e "${KEY_FILE}" ]] || die "platform PKI already exists; refusing import"
    install_pair "${source_cert}" "${source_key}"
    log "existing PKI adopted without changing certificate identity"
    ;;
  renew)
    validate_pair
    renew_cert
    log "certificate renewed; private key preserved"
    ;;
  recreate)
    [[ "${2:-}" == "--yes" ]] || die "recreate requires --yes"
    create_pair
    log "PKI recreated with a new private key"
    ;;
  delete)
    [[ "${2:-}" == "--yes" ]] || die "delete requires --yes"
    rm -f -- "${CERT_FILE}" "${KEY_FILE}"
    log "PKI deleted"
    ;;
  *)
    usage
    exit 2
    ;;
esac
