<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Stack 40 — Gitea + Runner

[Stack operations](../docs/operations.md) · [All stacks](../README.md#stacks-and-dependencies)

Stack4 provides the local Git service and an Actions runner. Gitea serves HTTP on `redlocal`; Stack1 is responsible for optional HTTPS publication. Gitea SSH may be published directly on the configured host port.

```mermaid
flowchart LR
    Users[Users / Git clients] -->|HTTPS via Stack1| Gitea[Stack4 Gitea]
    Users -->|SSH configured host port| Gitea
    Runner[Stack4 Actions runner] -->|internal HTTP| Gitea
    HermesMemory[Stack6 memory sync] -.->|optional git.remote| Gitea
    Gitea --> Repos[(Repositories and app state)]
```

## Contract

- **Requires:** Stack0.
- **Optional relationship:** Stack1 may publish the HTTP service.
- **Provides:** `git.remote` and `git.runner`.
- **Owns:** Gitea and runner containers plus their runtime areas.
- **Recovery:** Gitea application/repository state must be backed up separately. Runner registration/runtime can be reconstructed; the wrappers do not perform backup or restore.

Stack4's managed configuration files are source artifacts. PREPARE renders installation-specific values from protected operational configuration rather than embedding a second full configuration template inside shell code.

## Runtime ownership

Gitea and its runner have separate runtime areas. Existing runner registration identity may be preserved during ordinary local convergence, but it is operational runtime rather than durable DR authority: the manifest recovery contract backs up Gitea state only and reconstructs the runner when necessary.

Historical TLS-specific runner artifacts are not part of the current architecture. The runner reaches Gitea over internal HTTP on `redlocal`; external TLS termination belongs to Stack 10.

`.lock` means configuration and initial administrator setup completed. It does not prove the runner is registered or either service is running or healthy.

## Unattended preparation wrapper

Run `sudo ./local-ai stack-40 install` from the repository root. After checking Stack 00's lock, it creates only Stack 40's service directories using the scoped platform bootstrap, prepares configuration, then runs Gitea's idempotent `migrate` CLI command to initialize the empty SQLite schema before creating the configured administrator. Both CLI commands run in disposable containers; no long-lived Gitea or runner container is started. This initializes a fresh installation; it does not import or upgrade an older Gitea installation. Only after administrator initialization succeeds does it write `.lock`. An existing lock skips the install phases.

`sudo ./local-ai stack-40 start` runs `docker compose up -d` after checking `.lock`. Gitea and the runner then start; the runner's registration and health can be inspected with `status`. `stop` runs `docker compose down` without `--volumes`; it removes containers, not Gitea's bind-mounted state or `.lock`. Start is not a health check.

Run both lifecycle verbs as root; `stop` remains available if `.lock` is missing.

`python3 -B wrapper/bin/stack-40.py status` reports Gitea HTTP health and runner container health. The runner healthcheck requires its persistent registration marker; it cannot prove that the runner accepts or completes jobs. `status --deep` currently has no additional probe.

## Lifecycle

Use `wrapper/bin/stack-40.py` for installation, start, stop, and status. No wrapper performs upgrades or recovery. Re-preparation may converge managed configuration while preserving application runtime, but should only follow a reviewed removal of `.lock`.

## Security and recovery invariants

- Gitea application secrets and administrative credentials remain outside Git.
- Internal runner-to-Gitea traffic stays on `redlocal`; external TLS belongs to Stack1.
- Persistent Gitea identity/state is preserved across PREPARE and guarded operations.
- A reliable Gitea backup requires a separately reviewed procedure rather than copying an arbitrary live filesystem tree.
- Runner state must not be mistaken for a backup resource merely because Stack 40 owns its runtime directory.

Key implementation files: `docker-compose.yml`, `config/gitea/app.ini`, `config/gitea-runner/config.yaml`, `01-prepare.py`, and `deploy-gitea.py`.
