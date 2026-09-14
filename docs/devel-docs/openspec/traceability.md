<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# OpenSpec traceability

[← OpenSpec index](README.md) · [Documentation map](../../TOC.md)

Every tagged behavioural contract needs automated or qualified evidence. Contract tags are stable behaviour identifiers; implementation files and individual test names may evolve as long as equivalent evidence remains. Runtime qualification complements automated tests when a rule depends on real Docker, registry or application interaction.

## Platform and installation

### `PLATFORM-DEP-001`
Automated: `tests/test_openspec_contracts.py::test_PLATFORM_DEP_001_required_dependencies_are_declared`. Additional: manifest planner tests.

### `PLATFORM-RUNTIME-001`
Automated: installer/manifest and repository-layout tests. Additional: separation between declarative source (`STACKS_ROOT`) and mutable runtime (`BASE_PATH`).

### `INSTALL-PLAN-001`
Automated: `tests/test_installer.py` and install passthrough in `tests/test_management_cli.py`. Additional: `./local-ai install --plan ...` qualification.

### `INSTALL-LIFECYCLE-001`
Automated: `tests/test_openspec_contracts.py::test_INSTALL_LIFECYCLE_001_restart_reconcile_waits_ready` plus `tests/test_stack6_reconcile_ready.py`. Additional: representative runtime qualification of READY/reconcile sequencing.

### `INSTALL-LOCK-001`
Automated: `tests/test_installer.py`. Additional: stack PREPARE contracts.

## Disaster recovery

### `DR-BACKUP-001`
Automated: `tests/test_openspec_contracts.py::test_DR_BACKUP_001_stack7_artifact_is_declared` and `tests/disaster_recovery/test_dr_backup_all.py`. Additional: qualified global backup.

### `DR-BACKUP-002`
Automated: `tests/disaster_recovery/test_dr_backup_all.py` covers equal, descendant and ancestor overlap after resolved-path normalization, including symlink/`..` cases. Additional: runtime qualification rejected destinations equal to, nested under or ancestors of protected source/runtime roots before temporary or terminal publication.

### `DR-RESTORE-001`
Automated: `tests/disaster_recovery/test_dr_restore_all.py` plus restore-live/compat tests. Additional: qualified clean-target recovery and historical installer compatibility.

### `DR-STACK7-001`
Automated: `tests/test_openspec_contracts.py::test_DR_STACK7_001_restore_contract_preserves_data_and_identity`. Additional: [DR status](../../dr/status.md).

## Stack contracts

| Contract | Primary evidence |
|---|---|
| `STACK0-FOUNDATION-001` | recovery/manifest tests + Stack0 verify |
| `STACK1-INGRESS-001` | stack/install contracts + HAProxy qualification |
| `STACK2-WEB-001` | `tests/test_stack7_web_capabilities.py` |
| `STACK3-GATEWAY-001` | DR/recovery-contract tests + SDR-0003 |
| `STACK4-GIT-001` | `test_dr_stack4_restore_verify.py` |
| `STACK5-RECONSTRUCT-001` | recovery-contract tests |
| `STACK6-ISOLATION-001` | OpenSpec contract test + SDR-0002 |
| `STACK6-MEMORY-001` | `test_dr_stack6_verify.py` |
| `STACK7-POLICY-001` | OpenSpec contract test + SDR-0005 |
| `STACK7-WEB-001` | OpenSpec contract test + runtime web qualification |

See [per-stack feature contracts](stacks/README.md) and the [cross-stack architecture](../../stacks/README.md) for context.

## Management CLI

### Boundary and layout

- `CLI-BOUNDARY-001` — `tests/test_management_cli.py::test_cli_boundary_exposes_versioned_json_upgrade_contract`; [ADR-0002](../adr/0002-single-management-cli.md).
- `CLI-LAYOUT-001` — `tests/test_repository_layout.py::test_local_ai_is_the_supported_root_management_cli`; [ADR-0005](../adr/0005-unified-command-implementation-package.md).

### Machine-readable management contracts

- `CLI-JSON-001` — `tests/test_management_json_contracts.py` verifies structured install plan output and explicit execution confirmation without exposing private command lines.
- `CLI-JSON-002` — `tests/test_management_json_contracts.py` verifies the common restore action envelope and fail-closed normalization of private command failures.
- `CLI-DOCTOR-001` — `tests/test_doctor.py` verifies stable doctor payload semantics and deterministic prerequisite checks without requiring a live Docker daemon.

### Manifest component inventory

- `CLI-INVENTORY-001` — `tests/test_component_inventory.py` verifies that every owned container has one manifest component classification and that local/helper semantics are explicit; `commands/component_inventory.py` validates ownership and Compose service bindings.
- `CLI-INVENTORY-002` — `tests/test_component_inventory.py`, `tests/test_management_cli.py` and `tests/test_upgrade_policy.py` verify that upgrade metadata is compiled from current manifests and that the retired static component catalog is not part of repository layout. [ADR-0007](../adr/0007-manifest-component-inventory.md) is normative.
- `CLI-INVENTORY-003` — `tests/test_component_inventory.py` and `tests/test_management_cli.py` verify the public rescan command, source fingerprint, derived snapshot and structural diff semantics. Runtime qualification is not required because rescan deliberately performs no Docker/registry mutation.

### Selective runtime lifecycle

- `CLI-RUNTIME-001` — `tests/test_runtime_lifecycle.py` and `tests/test_management_runtime_cli.py`; runtime qualification confirms selective stop preserves the existing container and subsequent start returns the stack to READY/healthy.
- `CLI-RUNTIME-002` — `tests/test_runtime_lifecycle.py`; runtime qualification confirms that stopping a required provider while active consumers depend on it fails closed without mutating the provider.

### Registry discovery semantics

- `CLI-REGISTRY-001` — `tests/test_registry_failure_contract.py` injects HTTP 429/401/403 at the registry request boundary and proves `rate_limited`/`unauthorized`/`forbidden` propagate as `available=unknown`, never `current`. Positive registry discovery is separately runtime-qualified against the supported registry families used by configured images.
- `CLI-REGISTRY-002` — `tests/test_registry_discovery_cache.py` verifies TTL reuse, expiry, local-digest invalidation and bounded persistent cache size without contacting public registries.

### Upgrade execution

- `CLI-UPGRADE-001` — management CLI inventory coverage plus `tests/test_version_authority.py::test_human_upgrade_table_calls_runtime_version_installed`; human output uses Installed while JSON retains stable runtime fields.
- `CLI-UPGRADE-007` — `tests/test_upgrade_execution_metadata.py` verifies every upgrade-visible component has explicit execution metadata and guarded components remain distinct from inventory-only components.
- `CLI-UPGRADE-008` — [Upgrade executor qualification](../upgrade-qualification.md), execution metadata tests and representative runtime qualification establish that selectability is the result of an already-proven executor path, not a policy toggle.
- `CLI-UPGRADE-002` — `tests/test_upgrade_selection_policy.py` and `tests/test_version_authority.py`; installation-local plan includes concrete runtime baseline and immutable target digest.
- `CLI-UPGRADE-003` — management CLI proves `--yes` never auto-selects available versions.
- `CLI-UPGRADE-004` — stale plan fails before execution with `UPGRADE_PLAN_STALE`.
- `CLI-UPGRADE-005` — `tests/test_upgrade_executor.py`; targeted deployment and qualified single-component upgrade. Runtime qualification is required before newly promoted components are considered fully qualified.
- `CLI-UPGRADE-006` — executor/selection tests prove digest capture and moved-tag rejection before mutation.
- `CLI-UPGRADE-009` — executor failure tests plus the human apply contract prove `UPGRADE: PASS` is emitted only on successful guarded completion; failures remain journaled and do not become success merely because a container exists.
- `CLI-UPGRADE-010` — `tests/test_upgrade_force_override.py` verifies explicit administrative qualification bypass is stored only for a deterministic known mutation path, does not change manifest-declared selectability and does not authorize unrelated components. Runtime qualification includes an administrator-forced Dockhand update reported successful by the deployment operator; exact history/status evidence should be captured before final promotion decisions.

### Compatibility policy

- `CLI-POLICY-001` — local override and `clear` behaviour in `tests/test_upgrade_policy.py`.
- `CLI-POLICY-002` — newer target must remain in the same major/minor series; [ADR-0004](../adr/0004-upgrade-compatibility-policy.md).
- `CLI-POLICY-003` — major-series policy plus date-like version qualification.
- `CLI-POLICY-004` — manual policy uses an explicit target without series inference.
- `CLI-POLICY-005` — runtime qualification of `upgrade policy ... clear`.
- `CLI-POLICY-006` — policy changes invalidate incompatible selections without silently deleting them.
- `CLI-POLICY-007` — component `selectable` remains an independent support-qualification gate; an explicit forced selection is recorded separately rather than mutating that manifest fact.
- `CLI-POLICY-008` — executor revalidates policy before target preflight or mutation, including forced selections.

### Status

- `CLI-STATUS-001` — `tests/test_status.py` verifies the human table is stack-operational (`STACK`, `NAME`, `STATE`, `HEALTH`, `DRIFT`) and does not duplicate version columns from upgrade. Runtime state is derived from manifest/lifecycle ownership and required-container observations.
- `CLI-STATUS-002` — `commands/status.py` schema 3 plus `tests/test_status.py` preserve detailed component diagnostics alongside stack records; component drift vocabulary remains exactly `yes`, `no`, `n/a`.
- `CLI-STATUS-003` — `tests/test_status.py` exercises shared component identity semantics for fixed/floating references, registry failure and drift aggregation. `commands/component_state.py` owns these read-only identity/drift rules so status does not maintain a second interpretation of the same facts.

## Traceability maintenance

A new tagged scenario must be added here in the same change and must name real evidence. A test rename may update the evidence reference without renaming the behavioural tag. A removed behaviour must state whether it was superseded or retired; silently deleting its traceability entry is not sufficient.
