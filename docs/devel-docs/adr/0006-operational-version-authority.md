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
8. Upgrade executability is a separate safety decision. Externalizing a version does not automatically make a component selectable. A component is promoted to guarded/selectable only after identity, compatibility, mutation, migration, recovery, READY, VERIFY, dependency-impact, automated-test and representative runtime qualification gates pass.
9. Components qualified for the generic repository/version executor use exact repository/version keys and targeted Compose deployment. Current generic guarded components include HAProxy, Stack2 Redis, Stack2 RabbitMQ and Dockhand; Hermes and Open WebUI retain their existing guarded paths.
10. Immutable registry digest validation remains mandatory at selection/application time. Human versions and immutable identity remain separate facts as established by ADR-0003.

## Consequences

- Remote movement of tracking tags no longer changes installation intent on its own.
- A source update can provide newer fresh-install baselines without silently changing an adopted installation.
- `tracked-compose-pin` is not a meaningful generic execution blocker; blockers describe missing safety contracts such as `migration-policy-required`, `executor-not-qualified`, `local-build` or `non-versioned-component`.
- The protected operational `.env` carries non-secret component image/version authority and remains part of DR under ADR-0001.
- Registry-resolution logic remains necessary for discovery, immutable verification and migration of legacy moving tags, but it is not used to manufacture day-to-day installation intent.
- The operator workflow is intentionally simpler than the internal state model: **Installed → Available → Selectable → Selected → PASS**.
- `upgrade adopt` is a migration mechanism for older installations, not a normal recurring operator step.
- Marking a component selectable is a support commitment. The catalog flag records a qualified procedure; it is not a shortcut around qualification.
