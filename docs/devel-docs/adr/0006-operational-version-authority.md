<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# ADR-0006 — Operational component version authority

Status: Accepted

## Context

Container Compose files historically mixed two responsibilities: they described how a service runs and, for some components, they also followed mutable registry channels such as `alpine`, `3-alpine` or `3.0-alpine`. Registry discovery could correctly resolve the concrete running version and a newer available version, but `status` could then interpret the moving channel target as installation intent. That made a remote registry change appear as local Desired/Actual drift before the operator had selected an upgrade.

The guarded upgrade executor already uses installation-owned environment values for Hermes and Open WebUI. The same separation is needed for other externally versioned components.

## Decision

1. Git-tracked Compose remains the reproducible **source baseline** for a fresh installation, but moving image channels are not operational version authority.
2. Compose image references that participate in day-to-day version management use operational environment overrides with an exact source baseline fallback.
3. Existing installations adopt the exact already-running image/version through `./local-ai upgrade adopt --yes`. Adoption writes only missing non-secret image/version keys to the protected root `.env`; it never recreates containers or selects an upgrade.
4. Adoption fails closed when an existing operational value contradicts the observed runtime. It never silently overwrites operator-owned state.
5. `DESIRED` is therefore installation-owned configuration. Registry discovery contributes `AVAILABLE`; it does not manufacture operator intent.
6. Upgrade executability remains a separate safety decision. Externalizing a version does not automatically make a component selectable. Components requiring migration or compatibility work remain inventory-only with an explicit blocker.
7. Components qualified for the generic executor use exact repository/version keys and targeted Compose deployment. The first qualified extensions are HAProxy and Stack2 Redis.
8. Immutable registry digest validation remains mandatory at selection/application time. Human versions and immutable identity remain separate facts as established by ADR-0003.

## Consequences

- Remote movement of `redis:alpine` or `haproxy:3.0-alpine` no longer changes `DESIRED` on its own.
- A source update can provide newer fresh-install baselines without silently changing an adopted installation.
- `tracked-compose-pin` is no longer a meaningful generic execution blocker; remaining blockers describe actual missing safety contracts such as `migration-policy-required`, `executor-not-qualified` or `local-build`.
- The protected operational `.env` carries additional non-secret component image/version authority and remains part of DR under ADR-0001.
- Registry-resolution logic remains necessary for discovery, immutable verification and one-time adoption of legacy moving tags, but it is no longer needed to infer day-to-day installation intent.
