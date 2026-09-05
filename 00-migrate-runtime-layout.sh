#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_ROOT="/opt/docker"
STACKS_ROOT="/opt/docker/stacks"
RUNTIME_ROOT="/opt/docker/runtime"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

log() { printf '[layout] %s\n' "$*"; }
die() { printf '[layout] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "run as root"
[[ "${SCRIPT_DIR}" == "${STACKS_ROOT}" ]] || die "run this script from the checkout at ${STACKS_ROOT}; current repo root: ${SCRIPT_DIR}"
[[ -d "${STACKS_ROOT}/.git" ]] || die "${STACKS_ROOT} is not a Git working tree"

for cmd in docker find mv mkdir realpath; do
  command -v "$cmd" >/dev/null 2>&1 || die "missing required command: $cmd"
done

# Fail closed if any container is still running. This is a host-layout migration,
# not a live bind-mount move.
if docker ps -q | grep -q .; then
  docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' >&2
  die "containers are still running; stop the deployment before moving runtime directories"
fi

mkdir -p "${RUNTIME_ROOT}"

SOURCE_REAL="$(realpath -m -- "${SOURCE_ROOT}")"
RUNTIME_REAL="$(realpath -m -- "${RUNTIME_ROOT}")"
[[ "${RUNTIME_REAL}" == "${SOURCE_REAL}/runtime" ]] || die "unexpected runtime root: ${RUNTIME_REAL}"

mapfile -t services < <(find "${SOURCE_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'service_-_*' -printf '%f\n' | LC_ALL=C sort)

if (( ${#services[@]} == 0 )); then
  log "no legacy service_-_* directories found under ${SOURCE_ROOT}"
else
  log "services to migrate:"
  printf '  %s\n' "${services[@]}"
fi

# Preflight all destinations before moving anything.
for svc in "${services[@]}"; do
  src="${SOURCE_ROOT}/${svc}"
  dst="${RUNTIME_ROOT}/${svc}"
  [[ -d "${src}" && ! -L "${src}" ]] || die "invalid source directory: ${src}"
  [[ ! -e "${dst}" && ! -L "${dst}" ]] || die "destination already exists: ${dst}; no directories have been moved"
done

for svc in "${services[@]}"; do
  src="${SOURCE_ROOT}/${svc}"
  dst="${RUNTIME_ROOT}/${svc}"
  log "move ${src} -> ${dst}"
  mv -- "${src}" "${dst}"
done

# Audit.
if find "${SOURCE_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'service_-_*' -print -quit | grep -q .; then
  die "post-migration audit found service_-_* directories still under ${SOURCE_ROOT}"
fi

for svc in "${services[@]}"; do
  [[ -d "${RUNTIME_ROOT}/${svc}" ]] || die "post-migration target missing: ${RUNTIME_ROOT}/${svc}"
done

cat > "${RUNTIME_ROOT}/.layout-v2" <<EOF
stacks_root=${STACKS_ROOT}
runtime_root=${RUNTIME_ROOT}
migrated_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
chmod 0644 "${RUNTIME_ROOT}/.layout-v2"

log "runtime migration complete"
log "source checkout: ${STACKS_ROOT}"
log "persistent runtime: ${RUNTIME_ROOT}"
log "old stackX directories under /opt/docker were intentionally left untouched for rollback"
