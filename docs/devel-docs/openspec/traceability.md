<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# OpenSpec traceability

[← OpenSpec index](README.md) · [Documentation map](../../TOC.md)

Every tagged behavioural contract needs automated or qualified evidence. Contract tags are stable behaviour identifiers; implementation files and individual test names may evolve as long as equivalent evidence remains. Runtime qualification complements automated tests when a rule depends on real Docker, registry or application interaction.

The former three-column table was intentionally replaced: long test identifiers made GitHub hide the most useful columns on normal-width screens.

## Platform and installation

### `PLATFORM-DEP-001`
Automated: `tests/test_openspec_contracts.py::test_PLATFORM_DEP_001_required_dependencies_are_declared`. Additional: manifest planner tests.

### `PLATFORM-RUNTIME-001`
Automated: installer/manifest and repository-layout tests. Additional: `/opt/docker/stacks` versus `/opt/docker/runtime` ownership contract.

### `INSTALL-PLAN-001`
Automated: `tests/test_installer.py` and install passthrough in `tests/test_management_cli.py`. Additional: `./local-ai install --plan ...` qualification.

### `INSTALL-LIFECYCLE-001`
Automated: `tests/test_openspec_contracts.py::test_INSTALL_LIFECYCLE_001_restart_reconcile_waits_ready` plus `tests/test_stack6_reconcile_ready.py`. Additional: m92p installer/runtime qualification.

### `INSTALL-LOCK-001`
Automated: `tests/test_installer.py`. Additional: stack PREPARE contracts.

## Disaster recovery

### `DR-BACKUP-001`
Automated: `tests/test_openspec_contracts.py::test_DR_BACKUP_001_stack7_artifact_is_declared` and `tests/disaster_recovery/test_dr_backup_all.py`. Additional: qualified global backup.

### `DR-BACKUP-002`
Automated: `tests/disaster_recovery/test_dr_backup_all.py` covers equal, descendant and ancestor overlap after resolved-path normalization, including symlink/`..` cases. Additional: m92p CLI qualification rejected `/opt/docker/stacks`, `/opt/docker/runtime` and `/opt/docker` with RC=1 and no temporary backup-set residue.

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
| `STACK7-WEB-001` | OpenSpec contract test + live web qualification |

See [per-stack feature contracts](stacks/README.md) and the [cross-stack architecture](../../stacks/README.md) for context.

## Management CLI

### Boundary and layout

- `CLI-BOUNDARY-001` — `tests/test_management_cli.py::test_cli_boundary_exposes_versioned_json_upgrade_contract`; [ADR-0002](../adr/0002-single-management-cli.md).
- `CLI-LAYOUT-001` — `tests/test_repository_layout.py::test_local_ai_is_the_supported_root_management_cli`; [ADR-0005](../adr/0005-unified-command-implementation-package.md).

### Selective runtime lifecycle

- `CLI-RUNTIME-001` — `tests/test_runtime_lifecycle.py` and `tests/test_management_runtime_cli.py`; live m92p qualification stopped Stack5/Dockhand without removing its container and started it back to READY/healthy.
- `CLI-RUNTIME-002` — `tests/test_runtime_lifecycle.py`; live m92p qualification rejected stopping Stack3 while required consumers Stack6 and Stack7 were active, with RC=1 and no provider mutation.

### Registry failure semantics

- `CLI-REGISTRY-001` — `tests/test_registry_failure_contract.py` injects HTTP 429/401/403 at the registry request boundary and proves `rate_limited`/`unauthorized`/`forbidden` propagate as `available=unknown`, never `current`. Positive registry discovery is separately live-qualified against Docker Hub, GHCR and `docker.gitea.com`.

### Upgrade execution

- `CLI-UPGRADE-001` — management CLI inventory coverage plus `commands/upgrade-components.json`.
- `CLI-UPGRADE-002` — `tests/test_upgrade_selection_policy.py`; installation-local plan includes immutable target digest.
- `CLI-UPGRADE-003` — management CLI proves `--yes` never auto-selects available versions.
- `CLI-UPGRADE-004` — stale plan fails before execution with `UPGRADE_PLAN_STALE`.
- `CLI-UPGRADE-005` — `tests/test_upgrade_executor.py`; targeted deployment and qualified Hermes upgrade.
- `CLI-UPGRADE-006` — executor/selection tests prove digest capture and moved-tag rejection before mutation.

### Compatibility policy

- `CLI-POLICY-001` — local override and `clear` behaviour in `tests/test_upgrade_policy.py`.
- `CLI-POLICY-002` — newer target must remain in the same major/minor series; [ADR-0004](../adr/0004-upgrade-compatibility-policy.md).
- `CLI-POLICY-003` — major-series policy plus Hermes date-like version qualification.
- `CLI-POLICY-004` — manual policy uses an explicit target without series inference.
- `CLI-POLICY-005` — runtime qualification of `upgrade policy ... clear`.
- `CLI-POLICY-006` — policy changes invalidate incompatible selections without silently deleting them.
- `CLI-POLICY-007` — component `selectable` remains an independent gate.
- `CLI-POLICY-008` — executor revalidates policy before target preflight or mutation.

### Status

- `CLI-STATUS-001` — `tests/test_status.py` keeps Desired, Deployed and Actual separate.
- `CLI-STATUS-002` — drift vocabulary is exactly `yes`, `no`, `n/a`.
- `CLI-STATUS-003` — status tests cover floating tags, unchanged digests, fixed tags, digest pins, cross-command Actual consistency and registry-resolution failure. Runtime qualification on m92p observed HAProxy and Redis drift while RabbitMQ remained unchanged.

## Traceability maintenance

A new tagged scenario must be added here in the same change and must name real evidence. A test rename may update the evidence reference without renaming the behavioural tag. A removed behaviour must state whether it was superseded or retired; silently deleting its traceability entry is not sufficient.
