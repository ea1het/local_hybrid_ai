<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Stack4 — Gitea + Runner

[Documentation TOC](../docs/TOC.md) · [Stack map](../docs/stacks/README.md) · [OpenSpec contract](../docs/devel-docs/openspec/stacks/stack4.feature)

Stack4 provides the local Git service and its Actions runner. Gitea serves HTTP on `redlocal`; Stack1 is responsible for any HTTPS publication. The integrated SSH service is the exception and may be published directly on the configured host port.

```mermaid
flowchart LR
    Users[Users / Git clients] -->|HTTPS via Stack1| Gitea[Stack4 Gitea]
    Users -->|SSH configured host port| Gitea
    Runner[Stack4 Actions runner] -->|internal HTTP| Gitea
    HermesMemory[Stack6 memory sync] -. optional git.remote .-> Gitea
    Gitea --> Repos[(Repositories and app state)]
```

## Contract

- **Requires:** Stack0.
- **Provides:** local Git service and optional `git.remote` capability.
- **Persistence:** repositories, Gitea application state and runner registration identity.
- **DR:** controlled Gitea-native backup/restore; restored repositories are verified with Git integrity checks. Runner registration is reconstructable.

Stack4's managed configuration files are real source artifacts. PREPARE renders installation-specific values from the protected operational environment rather than embedding a second full configuration template inside shell code.

## Runtime ownership

Gitea and its runner have separate persistent runtime areas. The runner's runtime data includes its `.runner` identity and must not be casually replaced during configuration convergence.

Historical TLS-specific runner artifacts are not part of the current architecture: the runner reaches Gitea directly over internal HTTP on `redlocal`, while external TLS termination belongs to Stack1.

`.lock` means **PREPARED only**. It does not prove migrations have run, the configured administrator exists, the runner is registered or either service is healthy.

## Lifecycle

The supported lifecycle is orchestrated through `./local-ai`. Stack-owned prepare/run scripts describe implementation phases, but they are not operator APIs. Re-preparation may replace managed configuration while preserving application data and runner identity; it must not be used as a substitute for normal start/stop or upgrade operations.

## Security invariants

- Gitea application secrets and administrative credentials remain outside Git.
- Internal runner-to-Gitea traffic stays on `redlocal`; external TLS belongs to Stack1.
- Persistent Gitea identity/state is preserved across PREPARE and guarded upgrades.
- Backup/restore follows the Gitea recovery contract rather than copying an arbitrary live filesystem tree.
- `./local-ai` remains the supported management boundary.

## Related decisions

- [SDR-0004 — internal-only service networking](../docs/devel-docs/sdr/0004-internal-only-service-networking.md)
- [Gitea disaster recovery](../docs/dr/gitea.md)
- [Configuration and secrets](../docs/configuration/env-secrets.md)

Key implementation files: `docker-compose.yml`, `config/gitea/app.ini`, `config/gitea-runner/config.yaml`, `manifest.json`, and stack lifecycle scripts.
