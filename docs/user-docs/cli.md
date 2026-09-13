# `local-ai` command-line interface

`./local-ai` is the sole supported management interface for the project. Human-readable output is the default. `--json` requests the stable machine contract where that command supports one. Internal Python modules, shell scripts, Compose files and direct stack lifecycle commands are implementation details and may change without preserving their invocation syntax.

## Command map

```text
./local-ai
├── install <installer arguments...>
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

Global `--json` may be placed before the command. It is currently supported by `backup`, `restore`, `status` and `upgrade`; `install` deliberately returns `JSON_NOT_SUPPORTED` until an installer JSON schema is defined.

## `install`

`install` is a transparent public facade over the internal manifest-driven installer. The CLI does not reinterpret installer options; arguments such as `--plan`, `--dry-run`, `--target`, `--reconcile` and `--yes` pass through unchanged.

```bash
./local-ai install --plan all
./local-ai install --dry-run 7
./local-ai install 7 --yes
./local-ai install 7 --reconcile --yes
```

The lifecycle is `PREPARE -> DEPLOY -> READY -> RECONCILE -> VERIFY`. A stack `.lock` proves PREPARED only. Real execution requires root and `--yes`; planning and dry-run are read-only. Dependencies are resolved from manifests, and reconciliation is capability-driven rather than hard-coded by stack number.

## `backup`

```bash
./local-ai backup
./local-ai backup --destination /path/to/backup-root
./local-ai --json backup
```

Creates one atomic manifest-driven full recovery point. The protected operational `.env` is included as a sensitive global artifact. Stateful resources use stack-specific recovery strategies; reconstructable state is not copied merely because it exists at runtime.

## `restore`

`restore` exposes four public operations while keeping the DR implementation private.

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

The clean-target preflight proves that target paths and owned Docker objects are absent before a destructive recovery is allowed. Real execution additionally requires the internal restore command's explicit execution and clean-target confirmation flags; the CLI does not manufacture consent.

Stack6 Git-memory SSH material remains an external operator prerequisite and may be supplied through the supported bootstrap option during a real clean rebuild.

### `restore resume`

```bash
./local-ai restore resume /path/to/backup-set \
  --memory-sync-ssh-bootstrap /secure/bootstrap
```

Resumes the narrowly defined historical recovery path after a known post-reconcile readiness interruption. It validates restored source, `.env`, prepared state and durable data before continuing. New source uses `installer/install.py`; historical recovery points containing root `install.py` remain supported by the DR compatibility adapter.

## `status`

```bash
./local-ai status
./local-ai --json status
```

`status` is the installation-state view. Its public concepts are:

| Field | Meaning |
|---|---|
| `DESIRED` | Version encoded by this installation's declarative Compose/environment configuration. |
| `DEPLOYED` | Last version successfully applied by the guarded upgrade executor, or `unknown` when no executor history exists. |
| `ACTUAL` | Version observed from the running container image. |
| `DRIFT` | Comparison of desired versus actual; `unknown` when desired has no meaningful version. |

`DEPLOYED` is historical evidence, not a substitute for runtime observation. `ACTUAL` is never silently inferred from desired state.

## `upgrade check`

```bash
./local-ai upgrade check
./local-ai upgrade check --offline
./local-ai --json upgrade check
```

Online check discovers published versions from the **same container registry/package used by the configured/running image**. GitHub Releases are not mixed into operational container-version discovery. Offline check skips remote registry discovery.

At the time of this document, the human table still uses `CURRENT / AVAILABLE / SELECTED`. Point 10 closeout will remove the overloaded `CURRENT` presentation and align the view with `ACTUAL / AVAILABLE / POLICY / SELECTABLE / SELECTED / VALID`, while preserving the JSON v1 compatibility field during the transition. See the developer closeout plan.

Registry availability does not authorize execution. Compatibility policy and `selectable` are independent gates.

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

The project catalog supplies a default. An installation may override it in `/opt/docker/runtime/platform/upgrade-policy.json`. `clear` removes only the local override and returns to the project default. Policy changes never silently delete an existing selection; an incompatible selection is retained and reported invalid.

## Upgrade selection

```bash
./local-ai upgrade stack6 select <published-version>
./local-ai upgrade stack7 select <published-version>
./local-ai upgrade stack7 clear
```

Selection requires a component with executor support, a real target tag in the configured registry/package, a non-current target and an effective policy that permits the target. Multi-component stacks require the component name. The selection stores a baseline version so runtime changes after selection make the plan stale rather than silently changing the operation.

Stable rejection codes include `UPGRADE_COMPONENT_NOT_SELECTABLE`, `UPGRADE_TARGET_NOT_AVAILABLE`, `UPGRADE_TARGET_NOT_NEWER`, `UPGRADE_TARGET_UNSUPPORTED`, `UPGRADE_PLAN_STALE` and `UPGRADE_NOTHING_SELECTED`.

## `upgrade --yes`

```bash
./local-ai upgrade --yes
```

`--yes` confirms **exactly the targets already selected**. It never means "upgrade everything" and never auto-selects versions discovered by `upgrade check`.

Before mutation, the executor revalidates selection baselines, component selectability, effective compatibility policy and target-image existence. Components marked `recovery_required` receive a recovery point before desired-state mutation. The executor updates only the selected version keys, performs targeted deployment, waits READY, reconciles, waits READY again, verifies the target version and re-verifies prepared consumers affected through dependency/capability relationships. Successful selections are cleared and history is appended. Failures are journaled; destructive automatic rollback is not attempted.

Upgrade application is protected by a non-blocking installation-local lock. A concurrent apply fails with `UPGRADE_BUSY`.

## Human and JSON contracts

Human stack identifiers are numeric (`0` through `7`). JSON keeps stable identities such as `stack7`. JSON responses include a `schema_version`, a command identifier where applicable, `success`, structured data on success and a stable error object on failure. CLI implementation versioning and JSON contract versioning are independent.

The public contract is tested through `./local-ai`; unit tests may additionally exercise internals directly.
