#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

STACK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="${STACK_DIR}/.env"
DOCKERFILE="${STACK_DIR}/config/buzz/Dockerfile"

# Stack-managed reproducibility contract. Updating Buzz is a source change, not
# an implicit pull from a moving branch during deployment.
BUZZ_SOURCE_REPOSITORY="https://github.com/block/buzz.git"
BUZZ_SOURCE_REF="78618804ec86a014524ad7d1fb55928e8f5c3edf"
BUZZ_EXPECTED_CONTAINER_PATH="/opt/data/bin/buzz"

log() { printf '[buzz-prepare] %s\n' "$*"; }
die() { printf '[buzz-prepare] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "run as root"
[[ -f "${ENV_FILE}" ]] || die "missing ${ENV_FILE}"
[[ -f "${DOCKERFILE}" ]] || die "missing ${DOCKERFILE}"

for cmd in docker install stat mktemp cmp mv rm cat; do
  command -v "${cmd}" >/dev/null 2>&1 || die "missing required command: ${cmd}"
done

docker version >/dev/null 2>&1 || die "Docker is unavailable"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

for key in BASE_PATH HERMES_SERVICE HERMES_UID HERMES_GID HERMES_IMAGE HERMES_VERSION BUZZ_CLI_PATH; do
  [[ -n "${!key:-}" ]] || die "missing ${key} in ${ENV_FILE}"
done

[[ "${BASE_PATH}" == /* && "${BASE_PATH}" != "/" ]] || die "BASE_PATH must be an absolute non-root path"
[[ "${HERMES_SERVICE}" =~ ^service_-_[A-Za-z0-9._-]+$ ]] || die "unsafe HERMES_SERVICE"
[[ "${BUZZ_CLI_PATH}" == "${BUZZ_EXPECTED_CONTAINER_PATH}" ]] \
  || die "BUZZ_CLI_PATH must be ${BUZZ_EXPECTED_CONTAINER_PATH}"
[[ "${HERMES_VERSION}" != "latest" ]] || die "HERMES_VERSION cannot be latest"

HERMES_DATA="${BASE_PATH%/}/${HERMES_SERVICE}/data"
BIN_DIR="${HERMES_DATA}/bin"
BUZZ_HOST_PATH="${BIN_DIR}/buzz"
PROVENANCE="${BIN_DIR}/.buzz-source"
EXPECTED_PROVENANCE="${BUZZ_SOURCE_REPOSITORY}@${BUZZ_SOURCE_REF}"
BUILD_IMAGE="local-hybrid-ai-buzz-cli:${BUZZ_SOURCE_REF:0:12}"
EXTRACT_CONTAINER="local-hybrid-ai-buzz-extract-${BUZZ_SOURCE_REF:0:12}-$$"
TMP_DIR=""

cleanup() {
  docker rm -f "${EXTRACT_CONTAINER}" >/dev/null 2>&1 || true
  if [[ -n "${TMP_DIR}" && -d "${TMP_DIR}" ]]; then
    rm -rf -- "${TMP_DIR}"
  fi
  docker image rm "${BUILD_IMAGE}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

install -d -m 0750 -o "${HERMES_UID}" -g "${HERMES_GID}" "${BIN_DIR}"

validate_binary() {
  local container_path="$1"
  docker run --rm \
    --network none \
    --read-only \
    -v "${BIN_DIR}:/opt/data/bin:ro" \
    --entrypoint "${container_path}" \
    "${HERMES_IMAGE}:${HERMES_VERSION}" \
    --help >/dev/null 2>&1
}

# A correctly pinned binary can be reused. Manually installed or stale binaries
# are replaced atomically below; they are never treated as durable DR state.
if [[ -f "${BUZZ_HOST_PATH}" && ! -L "${BUZZ_HOST_PATH}" && -x "${BUZZ_HOST_PATH}" \
      && -f "${PROVENANCE}" && ! -L "${PROVENANCE}" ]]; then
  current_provenance="$(cat "${PROVENANCE}")"
  if [[ "${current_provenance}" == "${EXPECTED_PROVENANCE}" ]] \
      && validate_binary "${BUZZ_EXPECTED_CONTAINER_PATH}"; then
    chown "${HERMES_UID}:${HERMES_GID}" "${BUZZ_HOST_PATH}" "${PROVENANCE}"
    chmod 0755 "${BUZZ_HOST_PATH}"
    chmod 0640 "${PROVENANCE}"
    log "Buzz CLI already matches pinned source and runs inside Hermes image"
    exit 0
  fi
fi

log "building Buzz CLI from pinned source ${BUZZ_SOURCE_REF}"
docker build \
  --build-arg "BUZZ_SOURCE_REPOSITORY=${BUZZ_SOURCE_REPOSITORY}" \
  --build-arg "BUZZ_SOURCE_REF=${BUZZ_SOURCE_REF}" \
  -t "${BUILD_IMAGE}" \
  -f "${DOCKERFILE}" \
  "${STACK_DIR}/config/buzz" >/dev/null

# Extract only the compiled artifact. The source checkout and Rust toolchain stay
# inside the disposable build image and are not copied into platform runtime.
docker create --name "${EXTRACT_CONTAINER}" "${BUILD_IMAGE}" >/dev/null
TMP_DIR="$(mktemp -d "${BIN_DIR}/.buzz-install.XXXXXX")"
docker cp "${EXTRACT_CONTAINER}:/usr/local/bin/buzz" "${TMP_DIR}/buzz"
[[ -s "${TMP_DIR}/buzz" && ! -L "${TMP_DIR}/buzz" ]] || die "builder did not produce a regular non-empty buzz binary"

NEW_BINARY="${BIN_DIR}/.buzz.new.$$"
NEW_PROVENANCE="${BIN_DIR}/.buzz-source.new.$$"
install -m 0755 -o "${HERMES_UID}" -g "${HERMES_GID}" "${TMP_DIR}/buzz" "${NEW_BINARY}"
printf '%s\n' "${EXPECTED_PROVENANCE}" > "${NEW_PROVENANCE}"
chown "${HERMES_UID}:${HERMES_GID}" "${NEW_PROVENANCE}"
chmod 0640 "${NEW_PROVENANCE}"

# Validate ABI/runtime compatibility in the exact Hermes image before replacing
# the active binary.
validate_binary "/opt/data/bin/$(basename "${NEW_BINARY}")" \
  || die "compiled Buzz CLI does not run inside ${HERMES_IMAGE}:${HERMES_VERSION}"

mv -f -- "${NEW_BINARY}" "${BUZZ_HOST_PATH}"
mv -f -- "${NEW_PROVENANCE}" "${PROVENANCE}"

[[ -f "${BUZZ_HOST_PATH}" && ! -L "${BUZZ_HOST_PATH}" && -x "${BUZZ_HOST_PATH}" ]] \
  || die "Buzz CLI installation failed"
[[ "$(stat -c '%u:%g:%a' "${BUZZ_HOST_PATH}")" == "${HERMES_UID}:${HERMES_GID}:755" ]] \
  || die "Buzz CLI ownership/mode is incorrect"
[[ "$(cat "${PROVENANCE}")" == "${EXPECTED_PROVENANCE}" ]] \
  || die "Buzz CLI provenance mismatch"
validate_binary "${BUZZ_EXPECTED_CONTAINER_PATH}" \
  || die "installed Buzz CLI failed final Hermes-image validation"

log "Buzz CLI ready at ${BUZZ_HOST_PATH}"
log "Buzz remains optional at runtime; the binary is always pre-provisioned"
