<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Administrator-forced upgrades

[← User documentation](README.md) · [Normal upgrade workflow](upgrade.md) · [Executor qualification](../devel-docs/upgrade-qualification.md)

`SELECTABLE=no` means that the project does not claim the component's automated upgrade path is qualified and supported. It does **not** remove an administrator's ability to accept that risk explicitly when Local Hybrid AI already knows a deterministic mutation procedure for the component.

Use:

```bash
./local-ai upgrade <stack> <component> select <version> --force
./local-ai upgrade --yes
```

For example:

```bash
./local-ai upgrade stack5 dockhand select v1.0.48 --force
./local-ai upgrade --yes
```

The forced selection records that qualification was bypassed. A successful history entry therefore preserves that administrative decision instead of making the operation look like a normally supported upgrade.

## What `--force` bypasses

`--force` bypasses only the project's **qualification gate** for an inventory-only component. It means: "I understand this executor is not yet claimed as supported, and I explicitly accept that risk."

It does not bypass:

- target registry existence checks;
- immutable target digest capture and revalidation;
- stale-runtime detection;
- effective version policy;
- exact mutation scope declared by the owning stack manifest;
- recovery-point requirements already declared for the component;
- READY, RECONCILE and VERIFY processing;
- dependent-consumer re-verification;
- success/failure history semantics.

`./local-ai upgrade --yes` does not need a second force flag. The consent is part of the stored selection and is revalidated before execution.

## Components without an upgrade recipe

`--force` is not a raw escape hatch to run arbitrary Compose changes. If Local Hybrid AI has no deterministic mutation recipe for a component, selection fails with `UPGRADE_FORCE_UNAVAILABLE`.

This distinction is intentional: an administrator may override **support qualification**, but `local-ai` must still know which version authority to change and exactly which service to recreate. Adding a force-capable path for another component therefore requires describing that mutation in the owning stack's manifest metadata first.

## Clearing a forced selection

A forced inventory-only selection can be removed normally:

```bash
./local-ai upgrade <stack> <component> clear
```

Clearing never mutates the runtime.
