<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# ADR-0004: Upgrade compatibility is controlled by installation-owned policy

Status: Accepted

Date: 2026-09-13

## Context

Registry discovery answers whether a container artifact exists and which human version or immutable digest identifies it. It does not prove that the artifact is compatible with this platform, nor does it authorize deployment.

The installation also needs to remain in control of its own desired upgrade behaviour. An upstream project may publish a new minor or major release without that publication becoming an implicit upgrade decision for an existing Local Hybrid AI installation.

A large policy vocabulary would make the management contract harder to understand. The required behaviours can be expressed with three policy modes, while exceptional cases can be handled by explicit operator choice.

## Decision

Each catalog component declares a project `default_policy`. The only valid compatibility policies are:

- `minor-series`: an automatically compatible target must be strictly newer and remain in the same major.minor series.
- `major-series`: an automatically compatible target must be strictly newer and remain in the same major series.
- `manual`: no minor/major series boundary is inferred. The operator must explicitly name the exact target. If current and target are comparable semantic versions, a downgrade is still rejected. Non-semantic identities may be used only as explicit targets and remain subject to registry existence and executor checks.

The project default is not the installation decision. An installation may override any component policy locally. Overrides are stored outside the Git checkout and outside `.env` in installation runtime state. The effective policy is the installation override when present, otherwise the catalog `default_policy`.

`./local-ai` is the sole supported interface for policy management. Public stack selectors are numeric and match lifecycle/status display; internal identities such as `stack7` are not accepted as alternate operator selectors:

```text
./local-ai upgrade policy
./local-ai upgrade policy <0..7> [component]
./local-ai upgrade policy <0..7> [component] set minor-series
./local-ai upgrade policy <0..7> [component] set major-series
./local-ai upgrade policy <0..7> [component] set manual
./local-ai upgrade policy <0..7> [component] clear
```

The component form without an action shows the effective policy. `clear` removes only the installation override. It does not introduce a fourth policy and does not clear an upgrade selection; the catalog default becomes effective again. There is no public `show` action.

Policy and executor capability are independent. A target may satisfy compatibility policy while the component remains `selectable: false`. Such a component cannot be selected or executed through the supported upgrade path unless the explicitly constrained administrative force path applies.

Selection validates the exact target against the configured image registry/package, rejects a target that is not available, applies the current effective policy and refuses comparable downgrades. Availability alone is never authorization.

A policy change does not silently delete an existing selection. If the new effective policy no longer permits that target, the selection remains persisted for traceability and policy status reports it invalid. `upgrade --yes` rejects it with `UPGRADE_TARGET_UNSUPPORTED`.

The executor revalidates the current effective policy before target-image preflight, recovery-point creation or desired-state mutation. Validation performed when a target was selected is therefore not trusted indefinitely.

## Consequences

- Registry discovery, compatibility authorization, selection and execution remain distinct layers.
- Project defaults can evolve without overwriting an installation's explicit override.
- Installation policy state is mutable runtime state rather than source-controlled configuration.
- Operators may move freely between `minor-series`, `major-series` and `manual`.
- `manual` is an explicit-choice mode, not a synonym for incompatible or disabled.
- `selectable` remains a separate safety/executor capability gate.
- Existing selections remain auditable across policy changes and fail closed when they become unsupported.
- The executor cannot rely only on policy captured at selection time.
- Stack selection has one public representation: numeric ids.
