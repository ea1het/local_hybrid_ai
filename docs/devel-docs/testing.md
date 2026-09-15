<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Testing strategy and qualification

## Principles

The suite protects distinct public, architectural and internal boundaries. Apparent duplication is acceptable when tests prove different contracts or failure classes. Automated repository tests should be deterministic wherever practical; behaviour requiring real Docker, registry or application interaction additionally needs representative runtime qualification.

## Test layers

### Public management contract

`tests/test_management_cli.py`, management JSON tests and command-specific CLI tests protect `./local-ai` as the operator/automation anticorruption boundary: human identifiers, stable machine envelopes, installer passthrough, explicit upgrade selection and stable errors. They must not be replaced by direct imports when the public boundary itself is the contract.

### Installation, inventory and lifecycle

Installer, status, repository-layout, component-inventory and runtime-lifecycle tests protect manifest dependency resolution, PREPARED/READY semantics, reconciliation, source/runtime separation, semantic component discovery and selective start/stop safety. The retired static upgrade-component catalog must remain absent.

### Upgrade discovery, authority, policy and execution

Registry discovery, cache behaviour, tag ordering, latest-only digest handling, installation-owned version authority, adoption, compatibility policy, explicit selection, forced qualification bypass and guarded execution have separate tests. Discovery is fact gathering, selection is consent and execution is mutation; tests keep those boundaries separate.

### Shell completion

`tests/test_completion.py` protects source-local candidate generation, Bash/Zsh adapter generation, shell detection, target selection and idempotent file installation. Completion must not contact Docker or registries. Known candidate-grammar discrepancies that are not yet corrected belong in the active backlog and must not be documented as supported CLI syntax.

### Stack contracts

Stack-specific tests protect behaviour generic orchestration cannot prove, including Stack6 isolation/capability reconciliation and Stack7 model/web policy.

### Disaster recovery

`tests/disaster_recovery/` protects archive safety, filesystem rules, backup publication, planning, PostgreSQL logical recovery, Gitea-native recovery, clean-target enforcement, historical source compatibility, drills, staging and Stack6 external-memory prerequisites.

### Specification traceability

`tests/test_openspec_contracts.py` bridges tagged OpenSpec scenarios to explicit evidence. New behavioural tags require traceability entries; removed behaviour must be marked superseded/retired rather than silently disappearing.

## Regression rule: shared runtime identity semantics

Runtime qualification exposed a failure class in which stack status and version maintenance could interpret the same floating image differently. Permanent tests therefore protect these invariants:

1. Registry-backed component state and `upgrade` use the same runtime image identity/normalization semantics.
2. Floating-tag drift is determined from resolved artifact identity/digest, not equal tag text alone.
3. A moved floating tag changes desired registry identity while preserving the running actual identity and reports drift.
4. An unchanged floating tag reports no drift.
5. Pinned semantic tags and digest-pinned images preserve deterministic identity behaviour.
6. If required registry evidence cannot be obtained, status fails closed rather than synthesizing no drift.
7. `DEPLOYED` is orthogonal: guarded-upgrade history is authoritative when present; otherwise observed runtime identity is the adoption baseline.
8. `AVAILABLE` remains discovery only and must never become DESIRED/SELECTED implicitly.

Use component-agnostic fixtures and mocked registry/Docker boundaries for deterministic repository tests. A focused identity gate includes:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  tests.test_status \
  tests.test_version_sources \
  tests.test_container_registry \
  tests.test_registry_pinned_latest
```

If public CLI output or JSON changes, include `tests.test_management_cli`. If documentation/OpenSpec changes, include documentation-contract and OpenSpec-contract tests.

## Refactoring guidance

Shared fixtures and fake Docker/registry/CLI helpers are appropriate when they reduce setup duplication without removing behavioural assertions. DR compatibility tests that reference historical layouts remain valid only as explicit compatibility evidence for recovery points created by those layouts; historical names must not leak back into current operator documentation.

## Required gate

A repository change is fully qualified only after the complete suite passes:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'
```

Documentation changes must keep repository-layout, documentation-contract and OpenSpec traceability tests green. Runtime qualification must never be inferred from source-only evidence.
