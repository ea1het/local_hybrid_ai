<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Upgrade compatibility policy

[← Documentation map](TOC.md) · [Operator upgrade guide](user-docs/upgrade.md) · [Executor qualification](devel-docs/upgrade-qualification.md)

Container registry discovery answers **what exists**. Compatibility policy answers **which explicitly selected targets are compatible with this installation**. Executor qualification answers **whether local-ai is prepared to perform the change safely**. These are deliberately separate decisions.

The supported policy vocabulary is intentionally small:

| Policy | Automatic compatibility boundary |
|---|---|
| `minor-series` | strictly newer target in the same `major.minor` series |
| `major-series` | strictly newer target in the same `major` series |
| `manual` | no series inference; the operator explicitly names the exact target |

`manual` is not a disabled state. The exact target must still exist in the same configured container registry/package. When current and target are comparable semantic versions, a downgrade is rejected. Non-semantic identities are accepted only as explicit manual choices and remain subject to registry and executor validation.

## Project default and installation override

Each upgrade-visible component declares its project `default_policy` in the owning stack's `manifest.json`. The management CLI compiles this metadata dynamically from manifests; there is no second hand-maintained component catalog. An installation may override the project policy without modifying Git or `.env`.

Mutable overrides live in the installation runtime platform state (`upgrade-policy.json`). Inspect them through the supported CLI rather than editing that file directly:

```bash
./local-ai upgrade policy
./local-ai upgrade policy stack2 redis
./local-ai upgrade policy stack2 redis set major-series
./local-ai upgrade policy stack2 redis clear
```

`clear` removes only the local override and makes the project default effective again. It does not introduce a fourth policy and does not delete an upgrade selection.

## Policy and SELECTABLE are independent

A component can have `major-series` policy and still report `SELECTABLE=no`. In that case local-ai knows how to evaluate compatibility but has not yet qualified a safe automated executor for the component.

Changing policy therefore **cannot** turn a `NO SELECTABLE` component into a `SELECTABLE` one. Selectability requires the engineering qualification gates defined in [Upgrade executor qualification](devel-docs/upgrade-qualification.md).

This distinction is intentional: registry discovery and version comparison are much easier than proving mutation scope, migrations, recovery, READY, VERIFY and dependency effects.

## Selection validation

A selection must pass all relevant gates:

```text
exact target exists in configured registry/package
        ↓
component is SELECTABLE
        ↓
target is not already installed
        ↓
effective compatibility policy permits target
        ↓
exact target image + immutable digest recorded
        ↓
selection is persisted locally
```

Stable rejection codes include `UPGRADE_COMPONENT_NOT_SELECTABLE`, `UPGRADE_TARGET_NOT_AVAILABLE`, `UPGRADE_TARGET_NOT_NEWER`, `UPGRADE_TARGET_UNSUPPORTED`, `UPGRADE_TARGET_MOVED` and `UPGRADE_PLAN_STALE`.

Availability shown by `./local-ai upgrade` is therefore discovery state, not upgrade authorization. Apply resolves the selected tag again and rejects it before recovery or version-authority mutation if it no longer maps to the digest captured at selection.

## Existing selections and policy changes

Changing policy never silently clears a selected target. If an existing selection no longer satisfies the new effective policy, upgrade inventory reports it with `VALID=no`; the selection remains in the installation-local plan for traceability.

`./local-ai upgrade --yes` revalidates the current effective policy and fails before mutation when the selection is no longer allowed. Selections created before immutable target identity was introduced must be reselected rather than inferred.

## Machine-readable contract

Policy commands support the standard CLI JSON mode:

```bash
./local-ai --json upgrade policy
./local-ai --json upgrade policy stack2 redis
./local-ai --json upgrade policy stack2 redis set manual
./local-ai --json upgrade policy stack2 redis clear
```

A component policy record includes `default_policy`, `override_policy`, `effective_policy`, `selectable`, `selected` and `selection_valid`. Mutating responses also expose `previous_effective_policy` and the action performed; read-only show/list responses do not invent a previous transition.

The JSON contract version is independent from the private implementation and policy-state file schema.
