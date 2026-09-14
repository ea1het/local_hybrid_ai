<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# `local-ai` command-line interface

`./local-ai` is the sole supported management interface for the project. Human-readable output is the default. `--json` requests the stable machine contract where that command supports one. Python modules under `commands/`, shell scripts, Compose files and direct stack lifecycle commands are implementation details and may change without preserving their invocation syntax.

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
└── upgrade
    ├── check [--offline]
    ├── policy [stack [component] [set POLICY|clear]]
    ├── stack [component] select VERSION
    ├── stack [component] clear
    └── --yes
```

Global `--json` may be placed before the command. It is currently supported by `start`, `stop`, `backup`, `restore`, `status` and `upgrade`; `install` deliberately returns `JSON_NOT_SUPPORTED` until an installer JSON schema is defined.

## `install`

`install` is a transparent public facade over the private manifest-driven engine in `commands/install.py`. The CLI does not reinterpret installer options; arguments such as `--plan`, `--dry-run`, `--target`, `--reconcile` and `--yes` pass through unchanged.

```bash
./local-ai install --plan all
./local-ai install --dry-run 7
./local-ai install 7 --yes
./local-ai install 7 --reconcile --yes
```

The lifecycle is `PREPARE -> DEPLOY -> READY -> RECONCILE -> VERIFY`. A stack `.lock` proves PREPARED only. Real execution requires root and `--yes`; planning and dry-run are read-only. Dependencies are resolved from manifests, and reconciliation is capability-driven rather than hard-coded by stack number.

## `start` / `stop`

```bash
sudo ./local-ai stop 5
sudo ./local-ai start 5
sudo ./local-ai --json stop stack5
```

These commands expose selective runtime lifecycle through the supported management boundary. Stack selectors use the same manifest-driven forms accepted by the installer (`5`, `stack5`, or the manifest directory name). Exactly one stack must be selected.

`stop` performs a controlled `docker compose stop` in the stack directory. It never performs `docker compose down`, never removes networks or volumes, and never recreates containers. Before stopping a provider, the CLI checks required dependency/capability consumers that are currently running. If a required consumer would be broken, the operation fails closed with `STACK_HAS_ACTIVE_CONSUMERS` and makes no runtime change.

`start` performs a controlled `docker compose start`; it does not prepare, create or recreate a stack and it does not implicitly start required providers. The target must already be PREPARED and its required providers must already be running, otherwise the command fails closed. After start, generic READY is checked for the stack's `required_containers`; stack-specific application reconciliation remains part of the install/reconcile lifecycle rather than being silently run by `start`.

Stacks without managed runtime containers, such as Stack0, reject start/stop with `STACK_RUNTIME_EMPTY`. Real start/stop execution requires root. Human output reports the stack directory and all manifest-owned containers affected by the Compose operation; JSON responses use schema version `1` and command identifiers `runtime.start` / `runtime.stop`.

## `backup`

```bash
./local-ai backup
./local-ai backup --destination /path/to/backup-root
./local-ai --json backup
```

Creates one atomic manifest-driven full recovery point. The protected operational `.env` is included as a sensitive global artifact. Stateful resources use stack-specific recovery strategies; reconstructable state is not copied merely because it exists at runtime.

## `restore`

`restore` exposes four public operations while keeping the implementation in `commands/recovery/` private.

### `restore plan`

```bash
./local-ai restore plan /path/to/backup-set --dry-run
./local-ai --json restore plan /path/to/backup-set --dry-run
```

Validates the completed backup set, checks checksums, resolves stack order and prints restore actions. It makes no changes and refuses execution without `--dry-run`.

### `restore drill`

```bash
./local-ai restore drill /path/to/backup-set --destination /isolated/path
```

Runs an isolated end-to-end recovery drill. Drill containers do not publish ports, do not attach to the platform network and do not modify the live runtime.

### `restore apply`

```bash
./local-ai restore apply /path/to/backup-set --check-clean-target
```

The clean-target preflight proves that target paths and owned Docker objects are absent before a destructive recovery is allowed. Real execution additionally requires the underlying restore engine's explicit execution and clean-target confirmation flags; the CLI does not manufacture consent.

Stack6 Git-memory SSH material remains an external operator prerequisite and may be supplied through the supported bootstrap option during a real clean rebuild.

### `restore resume`

```bash
./local-ai restore resume /path/to/backup-set \
  --memory-sync-ssh-bootstrap /secure/bootstrap
```

Resumes the narrowly defined historical recovery path after a known post-reconcile readiness interruption. It validates restored source, `.env`, prepared state and durable data before continuing. Current source uses `commands/install.py`; historical recovery points containing `installer/install.py` or the older root `install.py` remain supported by the DR compatibility adapter. Those historical paths are not supported management APIs.

## `status`

```bash
./local-ai status
./local-ai --json status
```

`status` is the installation-state view. Its public concepts are:

| Field | Meaning |
|---|---|
| `DESIRED` | Effective version represented by this installation's declarative Compose/environment configuration. Fixed tags/digests are shown directly. Broad mutable tags such as `alpine`, major-only or major.minor tracking lines are resolved through their owning registry when possible. |
| `DEPLOYED` | Last version recorded by a successful guarded upgrade. If no guarded-upgrade history exists yet, the observed runtime version is used as the installation's adoption baseline. Components for which versioned deployment does not apply report `n/a`. `unknown` is reserved for a genuinely indeterminate deployed state. |
| `ACTUAL` | Version observed from the running container image. For mutable tracking tags, registry-native digest/tag mapping is used to expose the concrete running version rather than repeating the mutable tag name. |
| `DRIFT` | Fast Desired-versus-Actual decision: `yes` means they differ, `no` means they match, and `n/a` means drift cannot meaningfully be evaluated. |

For fixed references, Drift compares the fixed desired identity with the observed runtime identity. For mutable tracking references, Drift is based on immutable local-versus-remote digest evidence whenever available. If registry resolution is unavailable, `status` does **not** claim `no` merely because both source and runtime strings contain the same mutable tag; it reports `n/a` instead.

`DEPLOYED` remains historical evidence once guarded-upgrade history exists; the pre-history adoption fallback prevents an already-running installation from being mislabeled as unknown merely because it predates the executor. `ACTUAL` is never synthesized from desired state.

The status JSON contract is schema version `2`; the drift value vocabulary is `yes`, `no`, `n/a`.

## `upgrade check`

```bash
./local-ai upgrade check
./local-ai upgrade check --offline
./local-ai --json upgrade check
```

Online check discovers published versions from the **same container registry/package used by the configured/running image**. GitHub Releases are not mixed into operational container-version discovery. Offline check skips remote registry discovery.

The human update-decision table is:

```text
STACK COMPONENT ACTUAL AVAILABLE POLICY SELECTABLE SELECTED VALID
```

`ACTUAL` is the runtime observation shared with `status`. `AVAILABLE` describes registry discovery, `POLICY` is the effective installation compatibility policy, `SELECTABLE` is executor capability/authorization, `SELECTED` is explicit operator intent, and `VALID` reports whether an existing selection remains valid. Registry availability never creates consent.

## `upgrade policy`

```bash
./local-ai upgrade policy
./local-ai upgrade policy stack7
./local-ai upgrade policy stack4 gitea
./local-ai upgrade policy stack7 set major-series
./local-ai upgrade policy stack7 clear
```

Three policies exist:

| Policy | Meaning |
|---|---|
| `minor-series` | Target must be strictly newer and remain in the same `major.minor` series. |
| `major-series` | Target must be strictly newer and remain in the same `major` series. |
| `manual` | No series inference; the operator explicitly names the exact target. Comparable semantic downgrades remain rejected. |

The project catalog supplies a default. An installation may override it in `/opt/docker/runtime/platform/upgrade-policy.json`. `clear` removes only the local override and returns to the project default. Policy changes never silently delete an existing selection; an incompatible selection is retained and reported invalid. A read-only policy response has no previous transition; `previous_effective_policy` is emitted only for mutating `set`/`clear` responses.

## Upgrade selection

```bash
./local-ai upgrade stack6 select <published-version>
./local-ai upgrade stack7 select <published-version>
./local-ai upgrade stack7 clear
```

Selection requires a component with executor support, a real target tag in the configured registry/package, a non-current target and an effective policy that permits the target. Multi-component stacks require the component name.

The installation-local selection records:

- the runtime baseline (`current_at_selection`),
- the chosen human version/tag,
- the effective policy at selection,
- the exact target image reference, and
- the immutable registry digest observed for that target.

A runtime baseline change makes the plan stale. A selected registry tag that later points to a different digest is rejected rather than silently following the moved tag.

Stable rejection codes include `UPGRADE_COMPONENT_NOT_SELECTABLE`, `UPGRADE_TARGET_NOT_AVAILABLE`, `UPGRADE_TARGET_NOT_NEWER`, `UPGRADE_TARGET_UNSUPPORTED`, `UPGRADE_TARGET_MOVED`, `UPGRADE_PLAN_STALE` and `UPGRADE_NOTHING_SELECTED`.

## `upgrade --yes`

```bash
./local-ai upgrade --yes
```

`--yes` confirms **exactly the targets already selected**. It never means "upgrade everything" and never auto-selects versions discovered by `upgrade check`.

Before mutation, the executor revalidates selection baselines, component selectability, effective compatibility policy, target-image existence and immutable digest identity. Components marked `recovery_required` receive a recovery point only after those preflights pass. The executor updates only the selected version keys, performs targeted deployment, waits READY, reconciles, waits READY again, verifies the target version and re-verifies prepared consumers affected through dependency/capability relationships. Successful selections are cleared and history is appended. Failures are journaled; destructive automatic rollback is not attempted.

Upgrade application is protected by a non-blocking installation-local lock. A concurrent apply fails with `UPGRADE_BUSY`.

## Human and JSON contracts

Human stack identifiers are numeric (`0` through `7`). JSON keeps stable identities such as `stack7`. JSON responses include a `schema_version`, a command identifier where applicable, `success`, structured data on success and a stable error object on failure. CLI implementation versioning and JSON contract versioning are independent.

The public contract is tested through `./local-ai`; unit tests may additionally exercise private `commands/` modules directly.
