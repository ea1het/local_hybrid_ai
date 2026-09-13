# Testing strategy and cleanup audit

## Decision

The current suite is intentionally retained. The documentation refactor does **not** delete, merge or weaken behavioral tests. The most recent qualified m92p gate ran 262 tests successfully; those tests cover distinct lifecycle, registry, upgrade, security and disaster-recovery failure classes. A small amount of apparent duplication is acceptable where it protects different public and internal boundaries.

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

## Cleanup opportunities that are safe to consider later

Possible future refactoring includes shared fixture factories for repeated temporary runtime trees, shared fake Docker inspection helpers, common registry-probe fixtures and a small helper for CLI subprocess execution. These changes could reduce setup duplication while preserving every assertion and test case.

No current test is marked for deletion. In particular, DR compatibility tests that appear historical remain valuable because existing backup sets can refer to older source layouts such as root `install.py`.

## Required gates

Focused tests are useful during implementation, but a documentation/layout change is not considered qualified until the full suite passes:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'
```

Changes to documentation roots must additionally keep the repository-layout and OpenSpec traceability tests green. Public CLI changes must include `tests.test_management_cli` in the focused gate.
