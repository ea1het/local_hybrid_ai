<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# OpenSpec behavioural contracts

[Documentation TOC](../../TOC.md) · [Developer documentation](../README.md) · [Architecture decisions](../adr/README.md) · [Security decisions](../sdr/README.md) · [Traceability](traceability.md)

OpenSpec describes observable platform behaviour at the boundary between architecture, operator intent and executable verification. It is not a duplicate test suite and it is not a collection of implementation recipes. Each tagged scenario states a durable behaviour that should remain true even when the underlying Python, shell or Compose implementation changes.

## Contract layers

The specification is organized by concern:

```text
platform.feature                 repository/runtime ownership and shared platform invariants
installer.feature                lifecycle, dependency resolution and reconciliation semantics
disaster-recovery.feature        recovery-point completeness and safe reconstruction
features/management-cli.feature  sole public management boundary and state/upgrade/runtime semantics
features/upgrade-policy.feature  discovery, policy, selection and execution authorization
stacks/stack0..stack7.feature    stack-owned behaviour and security/persistence boundaries
```

See the [feature index](features/README.md), [per-stack feature index](stacks/README.md) and [cross-stack architecture map](../../stacks/README.md).

## Scenario rules

Every tagged scenario must have a stable identifier and explicit evidence in [traceability.md](traceability.md). Tags identify the contract, not a particular test function; implementation can be refactored while the behavioural identifier remains stable.

A useful scenario answers all of these questions:

1. **Context** — what installation/runtime condition exists?
2. **Trigger** — what supported lifecycle or management operation occurs?
3. **Positive result** — what observable behaviour must hold?
4. **Negative boundary** — what must *not* happen silently?
5. **Evidence** — which executable test or qualified runtime observation proves it?

OpenSpec deliberately avoids hard-coding internal filenames except when the path itself is the contract, for example the sole root `local-ai` entry point or installation-local policy state.

## Relationship to decisions and tests

ADRs explain architectural choices. SDRs explain security choices and accepted residual risk. Stack documentation explains the current component contract. OpenSpec turns the externally observable consequences of those decisions into durable behaviour identifiers.

Unit and integration tests may exercise internal modules because they need precise diagnostics. Public contract tests exercise `./local-ai`. OpenSpec sits above both: it explains why the assertions exist and which behaviour must survive implementation refactoring.

`tests/test_openspec_contracts.py` verifies that every tagged scenario is traceable and also enforces selected cross-cutting architecture invariants. `tests/test_documentation_contract.py` protects the minimum documentation structure. A tagged scenario without evidence is a specification defect.

## Change discipline

When behaviour changes:

1. update the relevant OpenSpec scenario;
2. update or add executable evidence;
3. update traceability;
4. update ADR/SDR when the change modifies an architectural or security decision;
5. update stack/operator documentation when the public contract changes;
6. qualify runtime-dependent behaviour in a representative deployment environment before claiming runtime verification.

Removing a scenario requires an explicit reason: superseded behaviour, retired feature or an architectural decision that makes the scenario obsolete. Specification reduction is not test cleanup.
