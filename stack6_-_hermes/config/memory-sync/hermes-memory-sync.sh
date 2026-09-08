#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

REPO="${MEMORY_SYNC_REPO:-/work/hermes-memory}"
BRANCH="${MEMORY_SYNC_BRANCH:-main}"
EXPECTED_ORIGIN="${MEMORY_SYNC_EXPECTED_ORIGIN:?Set MEMORY_SYNC_EXPECTED_ORIGIN}"
SSH_CONFIG="${MEMORY_SYNC_SSH_CONFIG:-/run/hermes-memory-ssh/ssh_config}"
LOCK_FILE="${MEMORY_SYNC_LOCK_FILE:-/tmp/hermes-memory-sync.lock}"

log()  { printf '[hermes-memory-sync] %s\n' "$*"; }
die()  { printf '[hermes-memory-sync] ERROR: %s\n' "$*" >&2; exit 1; }

for cmd in git ssh flock date sort sed; do
  command -v "${cmd}" >/dev/null 2>&1 || die "missing required command: ${cmd}"
done

[[ -d "${REPO}/.git" ]] || die "${REPO} is not a Git working tree"
[[ -f "${SSH_CONFIG}" ]] || die "missing SSH config: ${SSH_CONFIG}"

exec 9>"${LOCK_FILE}"
flock -n 9 || die "another sync is already running"

export GIT_SSH_COMMAND="ssh -F ${SSH_CONFIG}"
GIT=(git -c "safe.directory=${REPO}" -C "${REPO}")

origin="$("${GIT[@]}" remote get-url origin)"
[[ "${origin}" == "${EXPECTED_ORIGIN}" ]] || die "unexpected origin: ${origin}"

branch="$("${GIT[@]}" branch --show-current)"
[[ "${branch}" == "${BRANCH}" ]] || die "unexpected branch: ${branch}"

for file in MEMORY.md USER.md; do
  [[ -f "${REPO}/${file}" && ! -L "${REPO}/${file}" ]] || die "${file} missing, non-regular or symlink"
done

changed_paths="$({
  "${GIT[@]}" diff --name-only
  "${GIT[@]}" diff --cached --name-only
  "${GIT[@]}" ls-files --others --exclude-standard
} | sort -u | sed '/^$/d')"

if [[ -n "${changed_paths}" ]]; then
  while IFS= read -r path; do
    case "${path}" in
      MEMORY.md|USER.md) ;;
      *) die "unauthorized working-tree change: ${path}" ;;
    esac
  done <<< "${changed_paths}"
fi

dirty=false
if ! "${GIT[@]}" diff --quiet || \
   ! "${GIT[@]}" diff --cached --quiet || \
   [[ -n "$("${GIT[@]}" ls-files --others --exclude-standard)" ]]; then
  dirty=true
fi

log "fetch origin/${BRANCH}"
"${GIT[@]}" fetch --prune origin "${BRANCH}"
local_head="$("${GIT[@]}" rev-parse HEAD)"
remote_head="$("${GIT[@]}" rev-parse "origin/${BRANCH}")"

commit_memory() {
  "${GIT[@]}" add -- MEMORY.md USER.md
  "${GIT[@]}" \
    -c user.name="Hermes Memory Sync" \
    -c user.email="nhi-hermes@local" \
    commit -m "Sync Hermes memory $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
}

if [[ "${local_head}" == "${remote_head}" ]]; then
  if [[ "${dirty}" == true ]]; then
    log "local and remote aligned; committing memory"
    commit_memory
    log "push origin/${BRANCH}"
    "${GIT[@]}" push origin "HEAD:${BRANCH}"
  else
    log "no changes"
  fi
elif "${GIT[@]}" merge-base --is-ancestor "${local_head}" "${remote_head}"; then
  [[ "${dirty}" == false ]] || die "remote is ahead while local memory has changes; refusing automatic merge/rebase"
  log "remote ahead; fast-forward only"
  "${GIT[@]}" merge --ff-only "origin/${BRANCH}"
elif "${GIT[@]}" merge-base --is-ancestor "${remote_head}" "${local_head}"; then
  if [[ "${dirty}" == true ]]; then
    log "local ahead with new memory changes; committing"
    commit_memory
  fi
  log "local ahead; pushing"
  "${GIT[@]}" push origin "HEAD:${BRANCH}"
else
  die "Git history diverged; manual intervention required"
fi

"${GIT[@]}" fetch origin "${BRANCH}"
local_final="$("${GIT[@]}" rev-parse HEAD)"
remote_final="$("${GIT[@]}" rev-parse "origin/${BRANCH}")"
[[ "${local_final}" == "${remote_final}" ]] || die "final verification failed: local and remote differ"
[[ -z "$("${GIT[@]}" status --porcelain)" ]] || die "working tree is not clean after sync"

log "sync completed"
log "HEAD=${local_final}"
