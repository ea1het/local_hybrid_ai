#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -euo pipefail

AUTHORIZED_KEYS="/home/agent/.ssh/authorized_keys"
HOST_KEY="/etc/ssh/hostkeys/ssh_host_ed25519_key"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -s "${HOST_KEY}" ]] \
  || die "persistent SSH host key is missing: ${HOST_KEY}"

if [[ ! -s "${AUTHORIZED_KEYS}" ]]; then
  printf 'ERROR: authorized_keys is missing: %s\n' "${AUTHORIZED_KEYS}" >&2
  die "run 01-prepare.sh before starting the stack"
fi

# Initialize or validate the persistent lifecycle ledger before sshd accepts
# any Hermes execution. A corrupted/incomplete DB fails closed and is repaired
# explicitly with 02-cleanup.sh --reset-sandbox.
/usr/local/bin/hermes-sandbox-state-init

# /run is a tmpfs supplied by Compose. Runtime preparation is intentionally
# limited to transient sshd state plus lifecycle validation above.
mkdir -p /run/sshd

exec "$@"
