<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# `local-ai` command-line interface

[← User documentation](README.md) · [Documentation map](../TOC.md) · [Management plane](../architecture/management-plane.md)

`./local-ai` is the sole supported management interface for the project. Human-readable output is the default. `--json` requests the stable machine contract where that command supports one. Python modules under `commands/`, shell scripts, Compose files and direct stack lifecycle commands are implementation details.

## Stack selector contract

Every public command that identifies a stack uses the numeric stack id shown by `status` and `upgrade`: `0` through `7`. An operator supplies `7`, not `stack7` and not `stack7_-_open-webui`. Internal manifests and machine JSON may retain stable identities such as `stack7`; those are data identities, not alternate CLI selectors.

## Command map

```text
./local-ai
├── install <installer arguments...>
├── start <0..7>
├── stop <0..7>
├── backup [--destination PATH]
├── restore plan BACKUP_SET --dry-run
├── restore drill BACKUP_SET --destination PATH
├── restore apply BACKUP_SET <clean-target mode/options>
├── restore resume BACKUP_SET --memory-sync-ssh-bootstrap PATH
├── inventory rescan
├── status
├── doctor
├── completion bash|zsh|install|status
└── upgrade
    ├── [check] [--offline]
    ├── policy [0..7 [component] [set POLICY|clear]]
    ├── 0..7 [component] select VERSION [--force]
    ├── 0..7 [component] clear
    ├── adopt [--yes]
    └── --yes
```

Global `--json` may be placed before the command. It is supported only by management commands that expose a machine contract.

## `install`

```bash
./local-ai install --plan all
./local-ai install --dry-run 7
./local-ai install 7 --yes
./local-ai install 7 --reconcile --yes
./local-ai --json install 7 --plan
```

`install` is the public facade over the manifest-driven lifecycle engine. The lifecycle is `PREPARE -> DEPLOY -> READY -> RECONCILE -> VERIFY`. A stack `.lock` proves PREPARED only. Real execution requires root and `--yes`; planning and dry-run are read-only. Dependencies are resolved from manifests.

## `start` / `stop`

```bash
sudo ./local-ai stop 5
sudo ./local-ai start 5
```

`stop` performs controlled `docker compose stop`; it does not remove networks or volumes and fails closed when an active required consumer would be broken. `start` starts an already prepared/deployed stack; it does not prepare or recreate it and requires hard providers to be running. Generic READY is checked after start. Non-numeric selectors are rejected at the public CLI boundary.

## `backup` / `restore`

```bash
./local-ai backup
./local-ai backup --destination /path/to/backup-root
./local-ai restore plan /path/to/backup-set --dry-run
./local-ai restore drill /path/to/backup-set --destination /isolated/path
./local-ai restore apply /path/to/backup-set --check-clean-target
./local-ai restore resume /path/to/backup-set --memory-sync-ssh-bootstrap /secure/bootstrap
```

Backup creates one manifest-driven recovery point. The protected operational `.env` is sensitive global state. Managed resources use their declared recovery strategy; reconstructable resources are not promoted to backup artifacts merely because runtime files exist. Restore validation and clean-target gates belong to the recovery engine and the CLI never manufactures destructive consent. [DR documentation](../dr/README.md) describes the recovery phases.

## `inventory rescan`

```bash
./local-ai inventory rescan
./local-ai --json inventory rescan
```

Stack `manifest.json` files are the semantic source of component topology. Every owned container is classified as `versioned`, `local`, `helper` or `platform`; Compose is the implementation binding. Normal management compiles current manifests directly and does not depend on a generated static component catalog.

`inventory rescan` validates ownership/service bindings, calculates a source fingerprint and compares current topology with the previous derived snapshot. The snapshot is diagnostic history only. Rescan does not prepare/deploy/remove stacks, change `.env`, select upgrades or query registries. A removed component is reported, not implicitly authorized for runtime deletion.

## `status`

```bash
./local-ai status
./local-ai --json status
```

`status` answers whether the platform is operational and coherent. Human output is stack-oriented:

```text
STACK  NAME                  STATE     HEALTH    DRIFT
0      platform              prepared  ready     no
1      haproxy-web           running   ready     no
...
```

`STATE` describes lifecycle/runtime state, `HEALTH` is generic readiness from required container observations, and `DRIFT` aggregates component installation drift as `yes`, `no` or `n/a`. Application-specific VERIFY remains stack-owned.

The JSON diagnostic contract retains stack records plus detailed component `desired`, `deployed`, `actual` and `drift` dimensions for automation/troubleshooting. Human `status` deliberately does not duplicate the version table shown by `upgrade`.

## `doctor`

```bash
./local-ai doctor
./local-ai --json doctor
```

`doctor` is read-only and checks management prerequisites and installation metadata: entry point, manifests/lifecycle consistency, protected `.env` permissions, Docker, Compose, runtime-root prerequisites and component-inventory coherence. Human output uses `PASS`, `WARN` and `FAIL`; warnings do not make the command fail. It is not the runtime-status or version-maintenance view.

## `completion`

```bash
./local-ai completion install
./local-ai completion status
./local-ai completion bash
./local-ai completion zsh
```

`completion bash|zsh` prints a side-effect-free adapter. `completion install` detects supported Bash/Zsh from the operator environment and writes the generated adapter to the selected conventional target; `completion status` verifies that target against current generated content. The installer does not edit shell startup files. Completion follows the same numeric stack-selector grammar as the public CLI. [Shell completion](completion.md) contains the detailed contract.

## `upgrade`

The complete workflow is documented in [Upgrading Local Hybrid AI components](upgrade.md). The normal human version view is:

```bash
./local-ai upgrade
```

`./local-ai upgrade check` remains a compatibility alias. `--offline` skips remote registry discovery.

```text
STACK  COMPONENT  INSTALLED  AVAILABLE  POLICY  SELECTABLE  SELECTED  VALID
```

`INSTALLED` is concrete installed/running identity. `AVAILABLE` is registry discovery and never creates consent. `SELECTABLE=yes` means the project has qualified the guarded executor for that component. `SELECTED` is explicit operator intent and `VALID` says whether the stored selection still passes its gates.

A normal supported sequence is:

```bash
./local-ai upgrade
./local-ai upgrade 2 redis select 8.10.1-alpine3.23
./local-ai upgrade
sudo ./local-ai upgrade --yes
```

`select VERSION` validates and stores explicit upgrade intent without changing runtime. `clear` removes that stored selection without changing runtime:

```bash
./local-ai upgrade 2 redis clear
```

`upgrade --yes` applies only already-selected targets. Before mutation it revalidates runtime baseline, policy, target existence, immutable digest and executor eligibility. Required recovery, READY, reconciliation, VERIFY and dependent-consumer checks remain part of the guarded executor contract. Success ends with `UPGRADE: PASS`; absence of PASS is not success merely because a container exists.

### Administrator-forced upgrade

For `SELECTABLE=no`, an administrator can bypass project qualification only when a deterministic mutation recipe already exists:

```bash
./local-ai upgrade 5 dockhand select v1.0.48 --force
sudo ./local-ai upgrade --yes
```

Forced consent is stored in the selection. It does not bypass target existence/digest checks, stale-plan detection, compatibility policy, known mutation scope, recovery requirements, READY, VERIFY or consumer checks. If no deterministic recipe exists, selection fails with `UPGRADE_FORCE_UNAVAILABLE`. [Administrator-forced upgrades](forced-upgrades.md) describes the risk boundary.

### Selection and policy

```bash
./local-ai upgrade policy
./local-ai upgrade policy 2 redis
./local-ai upgrade policy 2 redis set major-series
./local-ai upgrade policy 2 redis clear
```

A policy command with no trailing action shows the effective policy. `set` writes the installation override. `policy ... clear` removes only that override and restores the manifest default; it does not remove a selected target. There is no public `show` action. Compatibility policy and support qualification are independent, so a policy override cannot make an unqualified component `SELECTABLE=yes`.

### `upgrade adopt`

```bash
./local-ai upgrade adopt
sudo ./local-ai upgrade adopt --yes
```

`adopt` is a migration utility for installations that predate installation-owned exact version authority. It records already-running identities without pulling images, running Compose, selecting an update or restarting services.

## Human and JSON contracts

The public human stack selector is numeric (`0` through `7`). Machine contracts preserve stable identities such as `stack7`. Machine responses include schema version, command identifier where applicable, structured success data and stable error objects. JSON-contract versioning is independent from private implementation details.
