#!/usr/bin/env bash
set -euo pipefail

AUTHORIZED_KEYS="/home/agent/.ssh/authorized_keys"
HOST_KEY="/etc/ssh/hostkeys/ssh_host_ed25519_key"

if [[ ! -s "${HOST_KEY}" ]]; then
  echo "ERROR: persistent SSH host key is missing: ${HOST_KEY}" >&2
  exit 1
fi

if [[ ! -s "${AUTHORIZED_KEYS}" ]]; then
  echo "ERROR: authorized_keys is missing: ${AUTHORIZED_KEYS}" >&2
  echo "ERROR: run 01-prepare.sh before starting the stack" >&2
  exit 1
fi

# Initialize or validate the persistent lifecycle ledger before sshd accepts
# any Hermes execution. A corrupted/incomplete DB fails closed and is repaired
# explicitly with 02-cleanup.sh --reset-sandbox.
/usr/local/bin/hermes-sandbox-state-init

# /run is a tmpfs supplied by Compose. Runtime preparation is intentionally
# limited to transient sshd state plus lifecycle validation above.
mkdir -p /run/sshd

exec "$@"
