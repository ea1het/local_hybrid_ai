<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Stack0 — Platform foundation

Stack0 is the mandatory foundation for every other stack. It owns the shared platform resources so application stacks do not duplicate or mutate them.

## What it provides

- **Service directory tree**: `00-bootstrap.py` creates every stack's `${BASE_PATH}/service_-_*` directories and sets their owner and mode in one place. The `01-prepare.py` scripts of Stacks 1–7 no longer create directories or fix their permissions; they only verify that they exist and copy/render their files into them.
- **`local-hybrid-pki` group** (`PLATFORM_PKI_GID`): lets HAProxy (uid 99) read the TLS private key.
- **Local CA trust**: `install-ca-cert.py` installs the mkcert CA (`rootCA.pem`) in the host trust store (`/usr/local/share/ca-certificates/${LOCAL_CA_NAME}.crt`).
- **HAProxy TLS material**: `install-tls-certs.py` installs the mkcert wildcard certificate as `${BASE_PATH}/service_-_haproxy/config/{tls.crt,tls.key}`. Stack1 later places `haproxy.cfg` in the same directory.
- **`redlocal`**: the shared external Docker bridge network (`NETWORK_NAME`).
- **Environment links**: `stack-NN_-_*/.env -> ../.env` for stacks 10–70, so `docker compose` in each stack reads the central `.env`.
- **`.lock`**: written by `install.py` only after 00–03 and `verify.py` have succeeded. It means PREPARED only, not deployed or healthy. See [`.lock` and running systems](#lock-and-running-systems).

Stack0 has no application container.

## Prerequisites

1. The worktree at `STACKS_ROOT` and the operational `.env` at `${STACKS_ROOT}/.env` (root:root 0600).
2. The certificate files copied from the mkcert CA (Mac mini) into `/tmp` — see [section 6 of the mkcert guide](../program_configs/inference_server/mkcert/README.md#6-use-the-certificate-on-the-stacks-server-stack0):

   | File | Consumed by |
   |---|---|
   | `/tmp/rootCA.pem` | `install-ca-cert.py` |
   | `/tmp/tls.crt` | `install-tls-certs.py` |
   | `/tmp/tls.key` | `install-tls-certs.py` |

   The scripts do not delete these files; remove at least `/tmp/tls.key` afterwards.

## Usage

Run as root:

```bash
cd /opt/docker/stacks/stack-00_-_platform
./install.py
```

`install.py` runs, in order:

```bash
00-bootstrap.py        # group + service directory tree of all stacks (--dry-run available)
01-prepare.py             # .env links, shared network
install-ca-cert.py        # /tmp/rootCA.pem -> host trust store
install-tls-certs.py      # /tmp/tls.{crt,key} -> service_-_haproxy/config (SAN checked against TLS_SAN_DOMAINS)
verify.py                 # read-only check of the above
# writes .lock atomically after successful verification
```

`01-prepare.py` never regenerates or overwrites the root `.env`, and refuses to replace an existing non-symlink `.env` inside a stack. Python scripts never write `__pycache__` into the worktree (`sys.dont_write_bytecode`, plus `python3 -B` and `PYTHONDONTWRITEBYTECODE=1` in `install.py`).

## `.lock` and running systems

`.lock` protects a system that is already running from being rewritten:

| Script | `stack-00_-_platform/.lock` present |
|---|---|
| `install.py` | Runs read-only `verify.py` and returns its result; does not repeat preparation. |
| `01-prepare.py` | Exits immediately; nothing changed. |
| `00-bootstrap.py` | Skips **every** stack whose own `stack-NN_-_*/.lock` exists (Stack0 included): its directories, owners and modes are left untouched, and no `docker run` is issued for it. Unlocked stacks are still created/reconciled. |
| `install-ca-cert.py` | Does nothing unless `--force` is given (CA rotation). |
| `install-tls-certs.py` | Does nothing unless `--renew` is given (certificate renewal). |
| `verify.py` | Read-only; works with or without `.lock` and checks the platform state. |

Stacks 1–7 follow the same convention: their `01-prepare.py` exits without changes when their `.lock` exists, and requires `stack-00_-_platform/.lock`. To reconcile a prepared stack deliberately, stop it, remove its `.lock` and run `00-bootstrap.py` and its `01-prepare.py` again.

If initial verification fails, `install.py` leaves no new `.lock` and a later run can retry preparation. An existing `.lock` is never removed automatically when a read-only verification fails.

### Existing installations with the old directory names

The source directories changed from `stack0_-_*` … `stack7_-_*` to `stack-00_-_*` … `stack-70_-_*`. In an existing checkout, Git may leave ignored `.lock` files and `.env` symlinks in the old directories. Check and migrate that local state during a maintenance window before running preparation from the new paths; a missing `.lock` would otherwise make a previously prepared stack eligible for reconciliation. Keep the central `${STACKS_ROOT}/.env` and `${BASE_PATH}` runtime data in place. The Compose project names remain `Stack1` … `Stack7`, so this source-directory rename does not itself rename those Docker projects.

**Renewing the certificate** on a running system: copy the new `tls.crt` / `tls.key` to `/tmp`, then

```bash
./install-tls-certs.py --renew
cd ../stack-10_-_haproxy_web && docker compose restart haproxy
```

## Files

| File | Purpose |
|---|---|
| `00-bootstrap.py` | Creates the `local-hybrid-pki` group and the service directory tree of every stack with its owner/mode. PGDATA directories are created only when absent and never modified afterwards. Stack2 directories are owned by the UID/GID of their images. |
| `01-prepare.py` | Idempotent preparation: `.env` links and shared Docker network. Requires `00-bootstrap.py`. |
| `install-ca-cert.py` | Installs the local CA in the host trust store and stops. Does not touch any stack. |
| `install-tls-certs.py` | Validates and installs `tls.crt` / `tls.key` for HAProxy. |
| `verify.py` | Read-only verification; prints `Stack0 READY`. |
| `install.py` | Runs 00 → 01 → 02 → 03 → verify. |

## Directory tree created by `00-bootstrap.py`

| Stack | Directories under `BASE_PATH` |
|---|---|
| 0 | `service_-_platform/{state,logs}` |
| 1 | `service_-_haproxy/config` (root:`PLATFORM_PKI_GID` 0750), `service_-_web` |
| 2 | `service_-_searxng/{config,data}`, `service_-_firecrawl-redis/data`, `service_-_firecrawl-rabbitmq/data`, `service_-_firecrawl-postgres/{data,secret}` |
| 3 | `service_-_litellm/config`, `service_-_litellm-postgres/{data,secret}` |
| 4 | `service_-_gitea/{config,config/conf,data}`, `service_-_gitea-runner/{data,secret}` |
| 5 | none (external Docker volume `dockhand_data`, managed by Stack5) |
| 6 | `${HERMES_SERVICE}/{config,config/ssh,data,logs}`, `${HERMES_MEMORY_SERVICE}/data`, `${MEMORY_SYNC_SERVICE}/ssh`, `${SANDBOX_SERVICE}/{config/ssh-host,data/home/.ssh,data/workspace,data/state,logs}` |
| 7 | `service_-_open-webui/data` |

Owners and modes are defined in `build_layout()` inside the script.

## Migrating from the former platform PKI

`pki.sh` and `${BASE_PATH}/service_-_platform/pki` are no longer used. On a server that was installed with the former layout:

```bash
# 0. Add TLS_SAN_DOMAINS to /opt/docker/stacks/.env (see .env.template).

# 1. Stack0 with the new flow (files already in /tmp). The old .lock was
#    written by the former 01-prepare.py; remove it so install.py runs.
#    00-bootstrap.py skips stacks 1-7 while their .lock exists.
cd /opt/docker/stacks/stack-00_-_platform
rm -f .lock && ./install.py

# 2. Re-prepare Stack1 (its .lock makes 01-prepare.py a no-op otherwise):
#    reconcile its directories, deploy haproxy.cfg and recreate HAProxy,
#    because the Compose file no longer mounts /etc/platform-pki.
cd /opt/docker/stacks/stack-10_-_haproxy_web
rm -f .lock
../stack-00_-_platform/00-bootstrap.py
./01-prepare.py
docker compose up -d --force-recreate haproxy

# 3. Remove the old PKI material (adjust to BASE_PATH)
rm -rf /opt/docker/runtime/service_-_platform/pki
```

## Variables

`STACKS_ROOT`, `BASE_PATH`, `NETWORK_NAME`, `ROOT_HOSTNAME`, `PLATFORM_PKI_GID`, `TLS_SAN_DOMAINS` (names the certificate must contain), `LOCAL_CA_NAME` (file name of the installed CA), plus the per-stack identities used for ownership (`GITEA_UID/GID`, `HERMES_UID/GID`, `SANDBOX_UID/GID`, the Stack6 `*_SERVICE` names and the Stack2 image variables) — see [`.env.template`](../.env.template).
