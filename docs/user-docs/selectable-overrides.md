<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Selectable overrides

[← User documentation](README.md) · [Normal upgrade workflow](upgrade.md) · [Executor qualification](../devel-docs/upgrade-qualification.md)

`SELECTABLE=no` means the project does not offer that component through the normal guarded upgrade path. Today exactly three components are non-selectable by manifest default, each for a reason that is not "qualification pending": `platform-foundation` (non-versioned), Stack4 `runner` (locally built, not sourced from a registry) and Stack6 `sandbox` (locally built). Every other component is selectable by default.

An administrator can still change the effective classification for any component, in either direction, with a persistent, auditable override:

```bash
./local-ai upgrade selectable <0..7> [component]
./local-ai upgrade selectable <0..7> [component] enable --yes
./local-ai upgrade selectable <0..7> [component] disable --yes
./local-ai upgrade selectable <0..7> [component] clear --yes
```

With no action, `selectable` shows the manifest default, any stored override and the effective classification for one component, or for every component when the stack/component selector is omitted. `enable` and `disable` persist an override in the installation's runtime area — never in the Git-tracked manifest. `clear` removes the override and returns the component to its manifest default.

For example, to select a target on a component that is non-selectable by manifest default:

```bash
./local-ai upgrade selectable 4 runner enable --yes
./local-ai upgrade 4 runner select <version>
./local-ai upgrade --yes
```

## What an override changes, and what it does not

Enabling an override changes only whether the component is *offered* for selection. It does not create a mutation recipe. A component still needs a manifest-declared `apply` recipe (the `EXECUTABLE` column shown by `upgrade selectable`) before `select`/`--yes` can act on it; attempting to apply a selection with no recipe fails with `UPGRADE_COMPONENT_NOT_EXECUTABLE`.

An override never bypasses any other gate: target registry existence, immutable digest capture and revalidation, stale-runtime detection, effective compatibility policy, exact mutation scope, recovery requirements, READY/RECONCILE/VERIFY or dependent-consumer re-verification. It changes only the selectable/non-selectable classification itself.

An override can also work in the opposite direction: `disable` can lock a normally selectable component closed, for example while an operator investigates an issue, without editing the manifest.

## Clearing an override

```bash
./local-ai upgrade selectable <0..7> [component] clear --yes
```

`clear` returns the component to its manifest default. It does not clear a staged upgrade selection; use `./local-ai upgrade <0..7> [component] clear` for that.
