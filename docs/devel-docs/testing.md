<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Testing strategy and qualification

## Principles

The test suite protects distinct public, architectural and internal boundaries. Apparent duplication is acceptable when two tests prove different contracts or failure classes. Test structure should be refactored only when equivalent coverage is demonstrable; reducing file or assertion count is not, by itself, a quality goal.

Automated tests and runtime qualification provide different evidence. Repository tests must remain deterministic wherever practical, while behaviour that depends on real Docker, registry or application interaction can additionally be qualified in a representative deployment environment.

## Test layers

### Public management contract

`tests/test_management_cli.py` exercises `./local-ai`. These tests protect the operator-facing anticorruption boundary: JSON shape, human stack identifiers, installer option passthrough, explicit upgrade selection and stable errors. They must not be replaced by direct imports of command internals when the public boundary itself is the contract.

### Installation state and lifecycle

`tests/test_installer.py`, `tests/test_status.py`, `tests/test_repository_layout.py` and lifecycle-specific tests protect dependency resolution, PREPARED/READY semantics, reconciliation behaviour, source layout and the desired/deployed/actual model.

### Upgrade discovery, policy and execution

Registry discovery, tag ordering, latest-only digest handling, compatibility policy, selection, guarded execution and concurrency have separate tests. They deliberately split discovery from authorization and authorization from mutation. Combining these into a single end-to-end test would reduce diagnostic precision without removing meaningful complexity.

### Stack contracts

Stack6 and Stack7 tests protect security and product behaviour that generic installer tests cannot prove: no Docker socket for Hermes, capability reconciliation, Open WebUI model policy and web capability behaviour.

### Disaster recovery

`tests/disaster_recovery/` covers independent safety boundaries: archive safety, filesystem rules, backup-set publication, planning, PostgreSQL logical recovery, Gitea native recovery, clean-target enforcement, historical installer compatibility, isolated drills, source staging and Stack6 external-memory prerequisites. These tests are not redundant merely because they exercise the same recovery subsystem.

### Specification traceability

`tests/test_openspec_contracts.py` checks that every tagged OpenSpec scenario has explicit evidence and also asserts selected architecture invariants directly. It is a bridge between prose/specification and executable tests, not a replacement for either.

## Regression rule: registry identity must cross subsystem boundaries

Runtime qualification exposed a semantic failure class that isolated tests had not caught: `status` can compare configured/running image tag text while `upgrade check` resolves registry-backed runtime identity. With mutable or partially floating image references, equal tag strings can hide different immutable artifacts and incorrectly report no drift.

Permanent regression tests therefore protect these cross-subsystem invariants:

1. Registry-backed `status.actual` and `upgrade check.actual` use the same runtime image identity and normalization semantics.
2. Floating-tag drift is determined from resolved artifact identity or digest, never only from equal tag text.
3. A moved floating tag produces a new desired registry identity, preserves the running identity as actual, and reports drift.
4. An unchanged floating tag reports no drift.
5. Pinned semantic tags and digest-pinned images preserve deterministic identity behaviour.
6. When floating-tag resolution cannot obtain the registry evidence required for a safe comparison, status fails closed and never synthesizes a no-drift result.
7. `DEPLOYED` remains orthogonal: guarded-upgrade history is authoritative when present; otherwise the observed runtime identity is the installation adoption baseline.

These tests should be component-agnostic. Representative Redis-, HAProxy- or RabbitMQ-like fixtures are appropriate, but production special cases should not be encoded solely to reproduce one deployment. Prefer existing `commands.upgrade_registry` helpers and mocked registry/Docker probes so automated tests remain deterministic and independent of the public Internet.

A focused gate for registry-identity changes includes at minimum:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  tests.test_status \
  tests.test_version_sources \
  tests.test_container_registry \
  tests.test_registry_pinned_latest
```

If the public CLI output or JSON contract changes, include `tests.test_management_cli`. After focused tests, run the complete repository suite and verify that generated Python caches and tracked worktree changes are absent.

## Refactoring guidance

Shared fixture factories, fake Docker inspection helpers, common registry-probe fixtures and CLI subprocess helpers are reasonable refactoring targets when they reduce setup duplication without removing assertions or behavioural cases.

DR compatibility tests that refer to historical source layouts remain valuable while recovery points created by those layouts are supported. Compatibility evidence should be retired only together with an explicit support-policy change.

## Required gates

Focused tests are useful during implementation, but a repository change is not considered fully qualified until the complete suite passes:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'
```

Changes to documentation roots must additionally keep repository-layout and OpenSpec traceability tests green. Public CLI changes must include `tests.test_management_cli` in the focused gate.
