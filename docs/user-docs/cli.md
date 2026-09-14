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
    ├── stack [component] select VERSION
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

### Plan

```bash
./local-ai restore plan /path/to/backup-set --dry-run
```

Validates the backup, checks checksums and prints restore actions without mutation.

### Drill

```bash
./local-ai restore drill /path/to/backup-set --destination /isolated/path
```

Runs an isolated recovery drill without modifying the active runtime.

### Apply

```bash
./local-ai restore apply /path/to/backup-set --check-clean-target
```

Real restore requires the clean-target and execution gates defined by the recovery engine. The CLI never manufactures destructive consent.

### Resume

```bash
./local-ai restore resume /path/to/backup-set \
  --memory-sync-ssh-bootstrap /secure/bootstrap
```

Resumes the narrowly defined historical recovery path after validation of restored state and prerequisites.

## `status`

```bash
./local-ai status
./local-ai --json status
```

`status` is a **diagnostic installation-state view**, not the normal way to decide whether software updates exist.

Internally Local Hybrid AI distinguishes configured intent, successful deployment history and observed runtime because those states are needed to detect drift and protect upgrades. Human `status` may therefore expose `DESIRED`, `DEPLOYED`, `ACTUAL` and `DRIFT` when diagnosing the installation.

For everyday package/version maintenance, use [`./local-ai upgrade`](upgrade.md). The normal operator questions are simpler: **what is installed, what is available, and can local-ai safely update it?**

A healthy component normally has aligned configured/deployed/runtime identities and `DRIFT=no`. Drift indicates that the installation intent and observed runtime disagree and should be understood before applying unrelated upgrades.

## `doctor`

```bash
./local-ai doctor
./local-ai --json doctor
```

`doctor` is read-only. It validates management-entry, manifest/lifecycle, protected `.env`, Docker, Compose and runtime-root prerequisites. Human output uses `PASS`, `WARN` and `FAIL`. A failed prerequisite returns non-zero; warnings do not.

## `upgrade`

The complete operator workflow is documented in [Upgrading Local Hybrid AI components](upgrade.md). Start here:

```bash
./local-ai upgrade
```

`./local-ai upgrade check` remains a compatibility alias for the same online inventory. `--offline` skips remote registry discovery.

The version table answers the normal maintenance questions:

```text
STACK  COMPONENT  INSTALLED  AVAILABLE  POLICY  SELECTABLE  SELECTED  VALID
```

`INSTALLED` is the concrete installed/running version and `AVAILABLE` is the newest version discovered from the component's configured registry/package. A newer `AVAILABLE` value never creates consent.

### SELECTABLE

`SELECTABLE=yes` means Local Hybrid AI has a qualified guarded executor for that component. The supported flow is:

```bash
./local-ai upgrade
./local-ai upgrade stack2 redis select 8.10.1-alpine3.23
./local-ai upgrade
sudo ./local-ai upgrade --yes
```

Selection is read-only with respect to the service. It verifies the target, compatibility policy and immutable registry digest, then records explicit operator intent.

`upgrade --yes` applies **only already-selected targets**. Before changing anything it revalidates the runtime baseline, component eligibility, policy and immutable target identity. The executor then performs the component's qualified mutation path, including READY/VERIFY and recovery/reconciliation steps where required.

A successful operation ends with:

```text
UPGRADE: PASS
```

That message means the supported guarded procedure completed and its required post-change verification passed. It does not merely mean that Docker started a container.

If `UPGRADE: PASS` is not produced, do not assume the update completed. Read the error/recovery point and inspect:

```bash
./local-ai status
./local-ai upgrade
```

Failures are journaled. Local Hybrid AI does not assume that destructive automatic rollback is safe.

Clear an unexecuted selection with:

```bash
./local-ai upgrade stack2 redis clear
```

### NO SELECTABLE

`SELECTABLE=no` does not mean upstream software is impossible to update. It means Local Hybrid AI has **not yet qualified a safe automated procedure** for that component.

Typical blocker meanings are:

| Blocker | Meaning |
|---|---|
| `migration-policy-required` | Migration/compatibility/recovery semantics still need an explicit contract. |
| `executor-not-qualified` | Discovery works but mutation/READY/VERIFY has not completed qualification. |
| `local-build` | Registry-version upgrade semantics do not apply normally. |
| `non-versioned-component` | Versioned package upgrade is not meaningful for this component. |

Changing upgrade policy does not turn a non-selectable component into a selectable one. Promotion requires identity, compatibility, mutation scope, migration, recovery, READY, VERIFY, dependency-impact, automated-test and real-runtime qualification gates. See [Upgrade executor qualification](../devel-docs/upgrade-qualification.md).

Once marked selectable, the project is asserting that `./local-ai upgrade` is a supported mutation path with defined success and failure semantics. The catalog flag is therefore the final record of qualification, not the mechanism that creates it.

### Upgrade policy

```bash
./local-ai upgrade policy
./local-ai upgrade policy stack2 redis
./local-ai upgrade policy stack2 redis set major-series
./local-ai upgrade policy stack2 redis clear
```

Policies are compatibility boundaries, independent of selectability:

| Policy | Meaning |
|---|---|
| `minor-series` | strictly newer target in the same `major.minor` series |
| `major-series` | strictly newer target in the same `major` series |
| `manual` | explicit target; no automatic series inference |

A policy override cannot bypass an unqualified executor.

### `upgrade adopt`

```bash
./local-ai upgrade adopt
sudo ./local-ai upgrade adopt --yes
```

`adopt` is an **installation migration utility**, not a normal update step. It records exact already-running identities as installation-owned authority for deployments that predate that model. It does not pull images, run Compose, select an update or restart services. Fresh installations should not need routine adoption.

## Human and JSON contracts

Human stack identifiers are numeric (`0` through `7`). JSON keeps stable identities such as `stack7`. Machine responses include a schema version, command identifier where applicable, structured success data and stable error objects. JSON-contract versioning is independent from private implementation details.
