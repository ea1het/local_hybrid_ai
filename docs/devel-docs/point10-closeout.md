<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Point 10 closeout — `local-ai` as the sole management interface

Point 10 is complete only when the public management boundary, state semantics, upgrade safety and disaster-recovery wrappers form one coherent operator contract. The source changes below are implemented on the command-unification branch; final closure still requires the complete m92p regression gate.

## Qualified foundations

The following behavior was already runtime-qualified before the package refactor:

- `./local-ai` is the sole supported root management entry point.
- Installer arguments such as `--plan` pass through the public CLI unchanged.
- Human stack identifiers are numeric while JSON preserves stable `stackN` identities.
- `status` exposes desired, deployed, actual and drift as distinct installation states.
- Container version discovery uses the same registry/package as the configured image.
- Compatibility policy is separate from registry availability and from executor capability.
- Explicit upgrade selection is installation-local; `--yes` never auto-selects.
- The guarded executor has a real successful Hermes upgrade qualification.
- Upgrade locking, failure journaling, target-image preflight, READY/reconcile/verify and dependent re-verification are implemented.
- Compatibility policies and installation overrides are qualified.

## Final source contract

### One public boundary, one private implementation package

`./local-ai` remains the only supported management interface. Its implementation is now rationalized under `commands/` rather than split across historical top-level `commands/`, `internal/`, `installer/` and `bkp-dr/` roots.

- install engine: `commands/install.py`
- lifecycle registry: `commands/install-lifecycle.json`
- status and upgrade implementation: `commands/*.py`
- upgrade component catalog: `commands/upgrade-components.json`
- backup/restore engines, adapters and schemas: `commands/recovery/`

Recovery remains a subpackage because it is a cohesive subsystem with multiple adapters and schemas. Stack-owned lifecycle scripts remain in their stack directories. See ADR-0005.

Historical recovery points are not invalidated by this reorganization: the DR compatibility layer may recognize recorded source containing current `commands/install.py`, previous `installer/install.py`, or the older root `install.py`. Those historical paths are restore compatibility only, not public interfaces.

### Installation state and upgrade state are separate

`./local-ai status` is the installation-state view:

```text
STACK COMPONENT DESIRED DEPLOYED ACTUAL DRIFT
```

`./local-ai upgrade check` is the update-decision view:

```text
STACK COMPONENT ACTUAL AVAILABLE POLICY SELECTABLE SELECTED VALID
```

`ACTUAL` is the shared runtime observation between both views. An upgrade selection does not become desired or deployed state merely because it exists.

### Policy JSON semantics

A policy read has no previous transition. `previous_effective_policy` is therefore reserved for mutating `set`/`clear` responses and is omitted from a read-only policy show/list response.

### Upgrade selection is bound to immutable artifact identity

Selection records the human registry tag/version together with the exact target image and registry digest observed at selection time. Apply resolves the target again before backup or desired-state mutation and fails closed with `UPGRADE_TARGET_MOVED` if the selected tag now points at a different digest.

The human version remains the operator-facing target; the digest is the immutable execution identity. Existing selections that predate immutable identity must be reselected rather than inferred.

### Recovery wrappers stay behind the CLI

The supported recovery surface remains:

```text
./local-ai backup
./local-ai restore plan ...
./local-ai restore drill ...
./local-ai restore apply ...
./local-ai restore resume ...
```

Automated CLI tests assert that these public actions dispatch only into `commands/recovery/`. The underlying Python files are private implementation details.

### Documentation and behavioral specification

Canonical architecture/security decisions and OpenSpec live under `docs/devel-docs/`. The duplicate root `openspec/` tree is removed. Repository-layout tests enforce the normalized roots, and OpenSpec traceability includes the unified command-package constraint.

## Final m92p gate still required

Source completion is not runtime qualification. Before Point 10 is declared closed, m92p must run a non-destructive regression gate that includes repository-layout tests, OpenSpec/traceability tests, management CLI/install/upgrade/registry tests, disaster-recovery tests and the complete unittest suite. Read-only CLI checks should cover status, upgrade inventory/policy and installer planning.

There is no reason to perform another real upgrade or destructive restore solely to validate this refactor; previously qualified executor and DR behaviors should be regression-tested without recreating their destructive evidence.

## Closure criterion

Point 10 closes when the command-unification source is merged, the final m92p gate is green, the working tree is clean and no generated Python caches are present. At that point external consumers have one supported interface (`./local-ai`), one coherent state vocabulary, immutable explicit upgrade intent, documented recovery operations, and one rational private implementation package behind the CLI.
