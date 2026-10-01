<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Stack 00 — Platform foundation

[Stack operations](../docs/operations.md) · [All stacks](../README.md#stacks-and-dependencies)

Stack0 is the mandatory foundation for every other stack. It owns the shared platform resources so application stacks do not duplicate or mutate them.

## What it provides

- **Service directory tree**: `00-bootstrap.py` owns the `${BASE_PATH}/service_-_*` directory layout. During Stack 00 `install`, it reconciles only platform directories and the HAProxy/web prerequisites needed by Stack 10. A direct invocation without `--platform-only` still visits all unlocked application stacks; use it only after reviewing their runtime state. Application prepare scripts verify that their directories exist.
- **`local-hybrid-pki` group** (`PLATFORM_PKI_GID`): lets HAProxy (uid 99) read the TLS private key.
- **Local CA trust**: `install-ca-cert.py` installs the mkcert CA (`rootCA.pem`) in the host trust store (`/usr/local/share/ca-certificates/${LOCAL_CA_NAME}.crt`).
- **HAProxy TLS material**: `install-tls-certs.py` installs the mkcert wildcard certificate as `${BASE_PATH}/service_-_haproxy/config/{tls.crt,tls.key}`. Stack1 later places `haproxy.cfg` in the same directory.
- **`redlocal`**: the shared external Docker bridge network (`NETWORK_NAME`).
- **Environment links**: `stack-NN_-_*/.env -> ../.env` for stacks 10–70, so `docker compose` in each stack reads the central `.env`.
- **`.lock`**: written by `install.py` only after 00–03 and `verify.py` have succeeded. It means PREPARED only, not deployed or healthy. See [`.lock` and running systems](#lock-and-running-systems).

Stack0 has no application container.

## Prerequisites

1. The worktree at `STACKS_ROOT` and the operational `.env` at `${STACKS_ROOT}/.env` (root:root 0600).
2. For missing, invalid, or deliberately rotated certificates, copy the mkcert files to the absolute paths configured in `.env` — see [section 6 of the mkcert guide](../program_configs/inference_server/mkcert/README.md#6-use-the-certificate-on-the-stacks-server-stack0). Defaults are under `/tmp`, but paths such as `/opt/temporal/rootCA.pem`, `/opt/temporal/tls.crt`, and `/opt/temporal/tls.key` are supported. Existing valid certificates do not require source files:

   | File | Consumed by |
   |---|---|
   | `LOCAL_CA_SOURCE_PATH` | `install-ca-cert.py` |
   | `TLS_CERT_SOURCE_PATH` | `install-tls-certs.py` |
   | `TLS_KEY_SOURCE_PATH` | `install-tls-certs.py` |

   The scripts do not delete source files. Keep `TLS_KEY_SOURCE_PATH` restricted to root and remove temporary copies when no longer needed.

## Usage

Run as root:

```bash
cd /opt/docker/stacks
sudo python3 -B wrapper/bin/stack-00.py install
```

The wrapper runs the complete stack-owned `install.py` workflow and relays its audit output. It never deploys containers. Direct `./install.py` invocation from the stack directory remains available.

`sudo python3 -B wrapper/bin/stack-00.py status` reports the preparation lock without changing anything; it cannot infer platform health from a lock. Add `--deep` to run the read-only `verify.py` checks of directories, permissions, Docker network, CA and TLS. Stack0 has no application containers to inspect.

`install.py` runs, in order:

```bash
00-bootstrap.py --platform-only  # group + platform and Stack 10 prerequisite directories
01-prepare.py             # .env links, shared network
install-ca-cert.py        # LOCAL_CA_SOURCE_PATH -> host trust store
install-tls-certs.py      # TLS_CERT_SOURCE_PATH / TLS_KEY_SOURCE_PATH -> service_-_haproxy/config
verify.py                 # read-only check of the above
# writes .lock atomically after successful verification
```

`01-prepare.py` never regenerates or overwrites the root `.env`, and refuses to replace an existing non-symlink `.env` inside a stack. Python scripts never write `__pycache__` into the worktree (`sys.dont_write_bytecode`, plus `python3 -B` and `PYTHONDONTWRITEBYTECODE=1` in `install.py`).

## `.lock` and running systems

`.lock` records a successful verification, but does not suppress the Stack0 audit. Each invocation checks platform resources and repairs missing or invalid state where safe; an existing valid certificate is preserved even when the configured sources are absent. Certificate rotation is separate and explicit (`install-ca-cert.py --force` or `install-tls-certs.py --renew`).

| Script | `stack-00_-_platform/.lock` present |
|---|---|
| `install.py` | Runs every phase, verifies the result and retains the existing lock; creates a lock only after success if missing. |
| `01-prepare.py` | Checks links and network, creating missing resources without replacing conflicting files. |
| `00-bootstrap.py` | During `install`, reconciles Stack 00 and platform-owned Stack 10 prerequisite directories even if Stack 10 has a lock. Direct invocation without `--platform-only` also reconciles unlocked application stacks; other locked stacks remain untouched. |
| `install-ca-cert.py` | Keeps a valid, trusted installed CA; refreshes missing bundle trust or repairs missing/invalid CA from `LOCAL_CA_SOURCE_PATH`. `--ca` overrides the source; `--force` rotates it explicitly. |
| `install-tls-certs.py` | Keeps a valid installed pair, repairs its metadata or reinstalls missing/invalid material from `TLS_CERT_SOURCE_PATH` and `TLS_KEY_SOURCE_PATH`. `--cert` / `--key` override the sources; `--renew` rotates explicitly. |
| `verify.py` | Read-only; works with or without `.lock` and checks the platform state. |

Stacks 10–70 skip their wrapper `install` when their `.lock` exists and require `stack-00_-_platform/.lock` for preparation. Stack 70 has its own `00-bootstrap.py` before `01-prepare.py`; the other application wrappers invoke only `01-prepare.py`. To reconfigure one deliberately, stop it, back up affected state, review the stack-specific instructions, and only then remove its lock and rerun its wrapper `install`.

If any phase fails, `install.py` removes an existing Stack0 `.lock` and leaves no new one; retry after correcting the reported cause. Other stacks must not treat a failed audit as READY. Back up sensitive state before deliberately rotating certificates or modifying running services.

### Existing installations with the old directory names

The source directories changed from `stack0_-_*` … `stack7_-_*` to `stack-00_-_*` … `stack-70_-_*`. In an existing checkout, Git may leave ignored `.lock` files and `.env` symlinks in the old directories. Check and migrate that local state during a maintenance window before running preparation from the new paths; a missing `.lock` would otherwise make a previously prepared stack eligible for reconciliation. Keep the central `${STACKS_ROOT}/.env` and `${BASE_PATH}` runtime data in place. The Compose project names remain `Stack1` … `Stack7`, so this source-directory rename does not itself rename those Docker projects.

**Renewing the certificate** on a running system: copy the new `tls.crt` / `tls.key` to the paths configured in `.env`, then

```bash
./install-tls-certs.py --renew
cd ../stack-10_-_haproxy_web && docker compose restart haproxy
```

## Files

| File | Purpose |
|---|---|
| `00-bootstrap.py` | Creates the `local-hybrid-pki` group and service directories. `--platform-only` limits reconciliation to Stack 00 and Stack 10 prerequisites; without it, all unlocked stacks are visited. PGDATA directories are never modified once present. |
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
| 2 | `service_-_searxng/{config,data}`, `service_-_firecrawl-redis/data`, `service_-_firecrawl-rabbitmq/data`, `service_-_firecrawl-postgres/data` |
| 3 | `service_-_litellm/config`, `service_-_litellm-postgres/data` |
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
#    written by the former 01-prepare.py; install.py now audits it too.
#    00-bootstrap.py skips stacks 1-7 while their .lock exists.
cd /opt/docker/stacks/stack-00_-_platform
./install.py

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
