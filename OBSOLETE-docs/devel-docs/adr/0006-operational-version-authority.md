<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# ADR-0006 — Operational component version authority

Status: Accepted

## Context

Container Compose files historically mixed two responsibilities: they described how a service runs and, for some components, they also followed mutable registry channels such as `alpine`, `3-alpine` or `3.0-alpine`. Registry discovery could correctly resolve the concrete running version and a newer available version, but `status` could then interpret the moving channel target as installation intent. That made a remote registry change appear as local Desired/Actual drift before the operator had selected an upgrade.

The guarded upgrade executor already used installation-owned environment values for some components. The same separation is needed for every externally versioned component that participates in managed upgrades.

A second problem is operator complexity. The internal state model needs configuration intent, deployment history, observed runtime and remote availability as separate facts, but exposing all of those concepts as the normal update workflow makes a simple question — "what do I have and can I update it?" — unnecessarily difficult.

## Decision

1. Git-tracked Compose remains the reproducible **source baseline** for a fresh installation, but moving image channels are not operational version authority.
2. Compose image references that participate in day-to-day version management use operational environment overrides with an exact source baseline fallback.
3. Existing installations adopt the exact already-running image/version through `./local-ai upgrade adopt --yes`. Adoption writes only missing non-secret image/version keys to the protected root `.env`; it never recreates containers or selects an upgrade.
4. Adoption fails closed when an existing operational value contradicts the observed runtime. It never silently overwrites operator-owned state.
5. Internally, `DESIRED` remains installation-owned configuration. Registry discovery contributes `AVAILABLE`; it does not manufacture operator intent.
6. The normal human upgrade interface does **not** require operators to reason about `DESIRED`. `./local-ai upgrade` presents the observed concrete runtime as `INSTALLED`, the registry result as `AVAILABLE`, and executor qualification as `SELECTABLE`. JSON may retain stable internal field names for compatibility.
7. `./local-ai status` remains the diagnostic state view and may expose Desired/Deployed/Actual/Drift because those distinctions are useful when diagnosing divergence.
8. Upgrade executability is a separate safety decision from version externalization, but it is not an earned promotion per component either: the project's default stance is that a component is selectable unless it has a concrete reason not to be. Exactly three components are non-selectable by manifest default (`platform-foundation`, Stack4 `runner`, Stack6 `sandbox`), each because it is not a registry-sourced versioned package, not because it is unqualified. Every other manifest-declared component is selectable by default. An administrator can still override the effective classification for any component in either direction with a persistent runtime override (see [selectable overrides](../../user-docs/selectable-overrides.md)). The identity, compatibility, mutation, migration, recovery, READY, VERIFY, dependency-impact, automated-test and representative-runtime-qualification gates ([upgrade executor qualification](../upgrade-qualification.md)) remain the engineering bar a component's guarded execution path is expected to meet; real-runtime qualification evidence exists today for Redis specifically, not as a precondition already proven for every selectable component.
9. Most versioned components use the generic `env-version` executor: exact repository/version keys and targeted Compose deployment. A component whose version transition is not safely reversible with a simple restart instead declares a dedicated recipe; Stack3 PostgreSQL's major-version transition is the current example (`postgres-major-upgrade`, requiring `--confirm-data-migration` in addition to `--yes`).
10. Immutable registry digest validation remains mandatory at selection/application time. Human versions and immutable identity remain separate facts as established by ADR-0003.

## Consequences

- Remote movement of tracking tags no longer changes installation intent on its own.
- A source update can provide newer fresh-install baselines without silently changing an adopted installation.
- `tracked-compose-pin` is not a meaningful generic execution blocker; blockers describe missing safety contracts such as `migration-policy-required`, `executor-not-qualified`, `local-build` or `non-versioned-component`.
- The protected operational `.env` carries non-secret component image/version authority and remains part of DR under ADR-0001.
- Registry-resolution logic remains necessary for discovery, immutable verification and migration of legacy moving tags, but it is not used to manufacture day-to-day installation intent.
- The operator workflow is intentionally simpler than the internal state model: **Installed → Available → Selectable → Selected → PASS**.
- `upgrade adopt` is a migration mechanism for older installations, not a normal recurring operator step.
- The manifest `selectable` flag records the project's default classification, not per-component earned qualification evidence; the three named exceptions are deliberate rather than a qualification backlog. A runtime override can change the effective classification for any component without editing the manifest and without bypassing any other gate.
