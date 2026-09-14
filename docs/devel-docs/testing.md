<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Testing strategy and cleanup audit

## Decision

The current suite is intentionally retained. The documentation refactor does **not** delete, merge or weaken behavioral tests. The most recent qualified m92p gate ran **277 tests successfully** after the registry-aware status identity fix; those tests cover distinct lifecycle, registry, upgrade, security and disaster-recovery failure classes. A small amount of apparent duplication is acceptable where it protects different public and internal boundaries.

The safe cleanup rule is: refactor test structure only when equivalence is provable; when uncertain, keep the test.

## Test layers

### Public management contract

`tests/test_management_cli.py` exercises `./local-ai`. These tests protect the operator-facing anticorruption boundary: JSON shape, human stack identifiers, installer option passthrough, explicit upgrade selection and stable errors. They should not be replaced by direct imports of command internals.

### Installation state and lifecycle

`tests/test_installer.py`, `tests/test_status.py`, `tests/test_repository_layout.py` and lifecycle-specific tests protect dependency resolution, PREPARED/READY semantics, reconciliation behavior, source layout and the desired/deployed/actual model.

### Upgrade discovery, policy and execution

Registry discovery, tag ordering, latest-only digest handling, compatibility policy, selection, guarded execution and concurrency have separate tests. They deliberately split discovery from authorization and authorization from mutation. Combining these into a single end-to-end file would reduce diagnostic precision without reducing meaningful complexity.

### Stack contracts

Stack6 and Stack7 tests protect security and product behavior that generic installer tests cannot prove: no Docker socket for Hermes, capability reconciliation, Open WebUI model policy and web capability behavior.

### Disaster recovery

`tests/disaster_recovery/` is large because DR has many independent safety boundaries: archive safety, filesystem rules, backup-set publication, planning, PostgreSQL logical recovery, Gitea native recovery, clean-target enforcement, historical installer compatibility, isolated drills, source staging and Stack6 external-memory prerequisites. These are not redundant merely because they all exercise recovery code.

### Specification traceability

`tests/test_openspec_contracts.py` checks that every tagged OpenSpec scenario has explicit evidence and also asserts a small set of architecture invariants directly. It is a bridge between prose/specification and executable tests, not a replacement for either.

## Regression lesson: registry identity must cross subsystem boundaries

A green suite previously failed to detect a real semantic defect: `status` compared configured/running image tag text while `upgrade check` resolved registry-backed runtime identity. With mutable or partially floating references such as `redis:alpine` or `haproxy:3.0-alpine`, equal tag strings could therefore hide different immutable artifacts and produce a false `DRIFT=no`.

Live m92p evidence that exposed the gap:

- Redis: local runtime resolved to `8.10.0-alpine3.23`, while the current `redis:alpine` registry target resolved to `8.10.1-alpine3.23`.
- HAProxy: local runtime resolved to `3.0.26-alpine3.24`, while the current `3.0-alpine` tracking target resolved to `3.0.27-alpine3.24`.
- RabbitMQ `3-alpine` resolved to the same `3.13.7-alpine` identity locally and remotely, providing the no-drift control case.

The missing coverage was not another isolated unit assertion; it was a **cross-subsystem invariant**. Permanent regression tests must protect the following rules:

1. Registry-backed `status.actual` and `upgrade check.actual` use the same runtime image identity and normalization semantics.
2. Floating-tag drift is determined from resolved artifact identity/digest, never only from equal tag text.
3. A moved floating tag produces `Desired=<new registry identity>`, `Actual=<running identity>`, `Drift=yes`.
4. An unchanged floating tag produces `Drift=no`.
5. Pinned semantic tags and digest-pinned images preserve deterministic identity behavior.
6. When floating-tag resolution cannot obtain the registry evidence required for a safe comparison, status fails closed and never synthesizes `Drift=no`.
7. `DEPLOYED` remains orthogonal: guarded-upgrade history is authoritative when present; otherwise the observed runtime identity is the installation adoption baseline.

These tests should be component-agnostic. Use representative Redis/HAProxy/RabbitMQ-like fixtures, but do not encode production special cases for those names. Prefer existing `commands.upgrade_registry` helpers and mocked registry/Docker probes so the tests remain deterministic and do not depend on the public Internet.

The focused gate for this regression work should include at minimum:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  tests.test_status \
  tests.test_version_sources \
  tests.test_container_registry \
  tests.test_registry_pinned_latest
```

If the public CLI output/JSON contract is touched, include `tests.test_management_cli`. After focused tests, run the complete repository suite and verify the worktree remains cache-clean and Git-clean.

## Cleanup opportunities that are safe to consider later

Possible future refactoring includes shared fixture factories for repeated temporary runtime trees, shared fake Docker inspection helpers, common registry-probe fixtures and a small helper for CLI subprocess execution. These changes could reduce setup duplication while preserving every assertion and test case.

No current test is marked for deletion. In particular, DR compatibility tests that appear historical remain valuable because existing backup sets can refer to older source layouts such as root `install.py`.

## Required gates

Focused tests are useful during implementation, but a documentation/layout change is not considered qualified until the full suite passes:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'
```

Changes to documentation roots must additionally keep the repository-layout and OpenSpec traceability tests green. Public CLI changes must include `tests.test_management_cli` in the focused gate.
