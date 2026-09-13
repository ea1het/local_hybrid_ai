# OpenSpec behavioral contracts

OpenSpec describes observable platform behavior at the boundary between architecture, operator intent and executable verification. It is not a duplicate test suite and it is not a collection of implementation recipes. Each tagged scenario states a durable behavior that should remain true even when the underlying Python, shell or Compose implementation changes.

## Contract layers

The specification is organized by concern:

```text
platform.feature                 repository/runtime ownership and shared platform invariants
installer.feature                lifecycle, dependency resolution and reconciliation semantics
disaster-recovery.feature        recovery-point completeness and safe reconstruction
features/management-cli.feature  sole public management boundary and state/upgrade semantics
features/upgrade-policy.feature  discovery, policy, selection and execution authorization
stacks/stack0..stack7.feature    stack-owned behavior and security/persistence boundaries
```

## Scenario rules

Every tagged scenario must have a stable identifier and explicit evidence in [`traceability.md`](traceability.md). Tags identify the contract, not a particular test function; implementation can be refactored while the behavioral identifier remains stable.

A useful scenario answers all of these questions:

1. **Context** — what installation/runtime condition exists?
2. **Trigger** — what supported lifecycle or management operation occurs?
3. **Positive result** — what observable behavior must hold?
4. **Negative boundary** — what must *not* happen silently?
5. **Evidence** — which executable test or qualified runtime observation proves it?

OpenSpec deliberately avoids hard-coding internal filenames except when the path itself is the contract (for example the sole root `local-ai` entry point or installation-local policy state).

## Relationship to tests

Unit/integration tests may exercise internal modules because they need precise diagnostics. Public contract tests exercise `./local-ai`. OpenSpec sits above both: it explains *why* the assertions exist and which behavior must survive implementation refactoring.

`tests/test_openspec_contracts.py` verifies that every tagged scenario is traceable and also enforces selected cross-cutting architecture invariants. A tagged scenario without evidence is a specification defect.

## Change discipline

When behavior changes:

1. update the relevant OpenSpec scenario;
2. update or add executable evidence;
3. update traceability;
4. update ADR/SDR when the change modifies an architectural or security decision;
5. update operator documentation when the public CLI or operating procedure changes;
6. qualify the change on m92p before claiming runtime verification.

Removing a scenario requires an explicit reason: superseded behavior, retired feature or an architectural decision that makes the scenario obsolete. Specification reduction is not test cleanup.
