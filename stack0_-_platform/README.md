<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Stack0 — Platform foundation

Stack0 is the mandatory foundation for every other stack. It owns the shared platform resources so application stacks do not duplicate or mutate them.

## What it provides

- **`redlocal`**: the shared external Docker bridge network (`NETWORK_NAME`).
- **Platform PKI**: wildcard certificate for `ROOT_HOSTNAME` at `${BASE_PATH}/service_-_platform/pki/{tls.crt,tls.key}`, readable by the `local-hybrid-pki` group (`PLATFORM_PKI_GID`). Stack1 consumes it read-only.
- **Runtime directory**: `${BASE_PATH}/service_-_platform/{pki,state,logs}`.
- **Environment links**: `stackN_-_*/.env -> ../.env` for stacks 1–7, so `docker compose` in each stack reads the central `.env`.
- **`.lock`**: written after a successful prepare. It means PREPARED only, not deployed or healthy.

Stack0 has no application container.

## Usage

Run as root, from a worktree located at `STACKS_ROOT`, with the operational `.env` at `${STACKS_ROOT}/.env` (root:root 0600).

```bash
cd /opt/docker/stacks/stack0_-_platform
./01-prepare.sh     # network, PKI group, runtime dirs, PKI, .env links, .lock
./verify.sh         # read-only check of the above
./install.sh        # 01-prepare.sh followed by verify.sh
```

`01-prepare.sh` never regenerates or overwrites the root `.env`, and refuses to replace an existing non-symlink `.env` inside a stack.

## Files

| File | Purpose |
|---|---|
| `01-prepare.sh` | Idempotent preparation of the shared foundation. |
| `pki.sh` | Create, import or inspect the platform certificate (`create`, `import`, `status`). Validity from `PLATFORM_CERT_DAYS`. |
| `verify.sh` | Read-only verification; prints `Stack0 READY`. |
| `install.sh` | Runs prepare, then verify. |

## Variables

`STACKS_ROOT`, `BASE_PATH`, `NETWORK_NAME`, `ROOT_HOSTNAME`, `PLATFORM_PKI_GID`, `PLATFORM_CERT_DAYS` — see the platform block of [`.env.template`](../.env.template).
