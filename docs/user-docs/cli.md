<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# `local-ai` command-line interface

`./local-ai` is the sole supported management interface for the project. Human-readable output is the default. `--json` requests the stable machine contract where that command supports one. Python modules under `commands/`, shell scripts, Compose files and direct stack lifecycle commands are implementation details.

## Command map

```text
./local-ai
├── install <installer arguments...>
├── start <stack>
├── stop <stack>
├── backup [--destination PATH]
├── restore plan BACKUP_SET --dry-run
├── restore drill BACKUP_SET --destination PATH
├── restore apply BACKUP_SET <clean-target mode/options>
├── restore resume BACKUP_SET --memory-sync-ssh-bootstrap PATH
├── status
├── doctor
└── upgrade
    ├── [check] [--offline]
    ├── policy [stack [component] [set POLICY|clear]]
    ├── stack [component] select VERSION [--force]
    ├── stack [component] clear
    ├── adopt [--yes]              # migration utility for older installations
    └── --yes
```

Global `--json` may be placed before the command. It is supported by the management commands that expose a machine contract.

## `install`

`install` is the public facade over the manifest-driven lifecycle engine.

```bash
./local-ai install --plan all
./local-ai install --dry-run 7
./local-ai install 7 --yes
./local-ai install 7 --reconcile --yes
./local-ai --json install 7 --plan
```

The lifecycle is `PREPARE -> DEPLOY -> READY -> RECONCILE -> VERIFY`. A stack `.lock` proves PREPARED only. Real execution requires root and `--yes`; planning and dry-run are read-only. Dependencies are resolved from manifests.

## `start` / `stop`

```bash
sudo ./local-ai stop 5
sudo ./local-ai start 5
sudo ./local-ai --json stop stack5
```

`stop` performs controlled `docker compose stop`; it never removes networks or volumes. It fails closed when an active required consumer would be broken. `start` starts an already prepared/deployed stack; it does not prepare or recreate it and requires providers to be running. Generic READY is checked after start.

## `backup`

```bash
./local-ai backup
./local-ai backup --destination /path/to/backup-root
./local-ai --json backup
```

Creates one manifest-driven recovery point. The protected operational `.env` is included as sensitive global state. Stateful resources use stack-specific recovery strategies; reconstructable resources are not copied merely because runtime state exists.

## `restore`

```bash
./local-ai restore plan /path/to/backup-set --dry-run
./local-ai restore drill /path/to/backup-set --destination /isolated/path
./local-ai restore apply /path/to/backup-set --check-clean-target
./local-ai restore resume /path/to/backup-set \
  --memory-sync-ssh-bootstrap /secure/bootstrap
```

Restore validation and clean-target gates belong to the recovery engine. The CLI never manufactures destructive consent.

## `status`

```bash
./local-ai status
./local-ai --json status
```

`status` answers the operational question **"is the platform up and coherent?"**. Human output is intentionally stack-oriented:

```text
STACK  NAME                  STATE     HEALTH    DRIFT
0      platform              prepared  ready     no
1      haproxy-web           running   ready     no
2      searxng-firecrawl     running   ready     no
...
```

The fields mean:

| Field | Meaning |
|---|---|
| `STATE` | Stack lifecycle/runtime state such as `unprepared`, `prepared`, `stopped`, `partial` or `running`. |
| `HEALTH` | Generic runtime readiness derived from required container state/health; application-specific VERIFY remains stack-owned. |
| `DRIFT` | Aggregated installation-version drift for components owned by the stack: `yes`, `no` or `n/a`. |

Human `status` deliberately does **not** duplicate the version table shown by `upgrade`.

The JSON diagnostic contract keeps both `stacks` and detailed `components`. Component records retain internal `desired`, `deployed`, `actual` and `drift` fields because automation and troubleshooting may need those distinctions. Those internal state dimensions are not the normal operator vocabulary for version maintenance.

Use `./local-ai upgrade` when the question is **"what version is installed and is an update available?"**.

## `doctor`

```bash
./local-ai doctor
./local-ai --json doctor
```

`doctor` answers **"are the management prerequisites and installation metadata sane?"**. It is read-only and checks the management entry point, manifest/lifecycle consistency, protected `.env` permissions, Docker, Compose and runtime-root prerequisites. Human output uses `PASS`, `WARN` and `FAIL`; warnings do not make the command fail.

`doctor` is not a runtime-status or version-maintenance command.

## `upgrade`

The complete operator workflow is documented in [Upgrading Local Hybrid AI components](upgrade.md). Start with:

```bash
./local-ai upgrade
```

This is the **only normal human version view**. `./local-ai upgrade check` remains a compatibility alias; new documentation and operator workflows should use `./local-ai upgrade`. `--offline` skips remote registry discovery.

The table is:

```text
STACK  COMPONENT  INSTALLED  AVAILABLE  POLICY  SELECTABLE  SELECTED  VALID
```

`INSTALLED` is the concrete installed/running version. `AVAILABLE` is registry discovery and never creates consent. `SELECTABLE=yes` means the project has qualified the guarded executor for that component. `SELECTED` is explicit operator intent and `VALID` tells whether that stored selection still passes its gates.

A supported upgrade flow is:

```bash
./local-ai upgrade
./local-ai upgrade stack2 redis select 8.10.1-alpine3.23
./local-ai upgrade
sudo ./local-ai upgrade --yes
```

`upgrade --yes` applies **only already-selected targets**. Before mutation it revalidates the runtime baseline, policy, target existence, immutable digest and executor eligibility. Required recovery, READY, reconciliation, VERIFY and consumer checks remain part of the guarded executor contract.

A successful operation ends with:

```text
UPGRADE: PASS
```

If PASS is absent, do not infer success merely because a container is running. Inspect `./local-ai status`, the upgrade error/recovery point and `./local-ai upgrade` before retrying or recovering.

### Administrator-forced upgrade

`SELECTABLE=no` means the project does not claim that path is qualified. An administrator may still accept that risk explicitly **when a deterministic mutation recipe already exists**:

```bash
./local-ai upgrade stack5 dockhand select v1.0.48 --force
./local-ai upgrade --yes
```

The forced consent is stored in the selection; a second force flag is not required at apply time. `--force` bypasses project qualification only. It does not bypass target existence, digest validation, stale-plan detection, compatibility policy, known mutation scope, recovery requirements, READY, VERIFY or dependent-consumer checks.

If no deterministic mutation recipe exists, force selection fails with `UPGRADE_FORCE_UNAVAILABLE` rather than degrading into an arbitrary Compose operation. See [Administrator-forced upgrades](forced-upgrades.md).

Selections can be cleared without changing runtime:

```bash
./local-ai upgrade stack2 redis clear
```

### Upgrade policy

```bash
./local-ai upgrade policy
./local-ai upgrade policy stack2 redis
./local-ai upgrade policy stack2 redis set major-series
./local-ai upgrade policy stack2 redis clear
```

Policies are compatibility boundaries, independent of support qualification. A policy override cannot by itself make an unqualified component `SELECTABLE=yes`.

### `upgrade adopt`

```bash
./local-ai upgrade adopt
sudo ./local-ai upgrade adopt --yes
```

`adopt` is an installation migration utility for deployments that predate installation-owned exact version authority. It records already-running identities; it does not pull images, run Compose, select an update or restart services.

## Human and JSON contracts

Human stack identifiers are numeric (`0` through `7`). JSON keeps stable identities such as `stack7`. Machine responses include a schema version, command identifier where applicable, structured success data and stable error objects. JSON-contract versioning is independent from private implementation details.
