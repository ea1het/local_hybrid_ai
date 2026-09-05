#!/usr/bin/env bash
set -Eeuo pipefail

STACKS_ROOT="/opt/docker/stacks"
RUNTIME_ROOT="/opt/docker/runtime"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

log() { printf '[env-layout] %s\n' "$*"; }
die() { printf '[env-layout] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "run as root"
[[ "${SCRIPT_DIR}" == "${STACKS_ROOT}" ]] || die "run from ${STACKS_ROOT}; current repo root: ${SCRIPT_DIR}"
[[ -d "${STACKS_ROOT}/.git" ]] || die "${STACKS_ROOT} is not a Git working tree"

for cmd in awk grep mktemp mv chmod chown stat; do
  command -v "$cmd" >/dev/null 2>&1 || die "missing required command: $cmd"
done

stacks=(
  stack1_-_haproxy_web
  stack2_-_searxng_firecrawl
  stack3_-_litellm
  stack4_-_gitea
  stack5_-_dockhand
  stack6_-_hermes
)

# Preflight: require every operational .env before modifying any of them.
for stack in "${stacks[@]}"; do
  env_file="${STACKS_ROOT}/${stack}/.env"
  [[ -f "${env_file}" && ! -L "${env_file}" ]] || die "missing operational env: ${env_file}; restore your saved .env files first"
done

for stack in "${stacks[@]}"; do
  env_file="${STACKS_ROOT}/${stack}/.env"
  tmp="$(mktemp "${env_file}.tmp.XXXXXX")"
  uid="$(stat -c '%u' "${env_file}")"
  gid="$(stat -c '%g' "${env_file}")"
  mode="$(stat -c '%a' "${env_file}")"

  awk -v stacks_root="${STACKS_ROOT}" -v runtime_root="${RUNTIME_ROOT}" '
    BEGIN { seen_stacks=0; seen_base=0 }
    /^STACKS_ROOT=/ {
      print "STACKS_ROOT=" stacks_root
      seen_stacks=1
      next
    }
    /^BASE_PATH=/ {
      print "BASE_PATH=" runtime_root
      seen_base=1
      next
    }
    { print }
    END {
      if (!seen_stacks) print "STACKS_ROOT=" stacks_root
      if (!seen_base) print "BASE_PATH=" runtime_root
    }
  ' "${env_file}" > "${tmp}"

  [[ "$(grep -c '^STACKS_ROOT=' "${tmp}")" -eq 1 ]] || die "invalid STACKS_ROOT count generated for ${env_file}"
  [[ "$(grep -c '^BASE_PATH=' "${tmp}")" -eq 1 ]] || die "invalid BASE_PATH count generated for ${env_file}"
  grep -qx "STACKS_ROOT=${STACKS_ROOT}" "${tmp}" || die "STACKS_ROOT audit failed for ${env_file}"
  grep -qx "BASE_PATH=${RUNTIME_ROOT}" "${tmp}" || die "BASE_PATH audit failed for ${env_file}"

  chown "${uid}:${gid}" "${tmp}"
  chmod "${mode}" "${tmp}"
  mv -f -- "${tmp}" "${env_file}"
  log "adapted ${stack}/.env"
done

log "all operational .env files now use:"
log "  STACKS_ROOT=${STACKS_ROOT}"
log "  BASE_PATH=${RUNTIME_ROOT}"
log "no other key/value is intentionally changed"
