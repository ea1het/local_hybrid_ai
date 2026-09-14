<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Component version authority

[← User documentation](README.md) · [Upgrade guide](upgrade.md) · [ADR-0006](../devel-docs/adr/0006-operational-version-authority.md)

This page is migration and advanced background. It is **not** the normal operator upgrade workflow. For day-to-day updates, start with [`./local-ai upgrade`](upgrade.md).

Local Hybrid AI keeps an installation-owned version authority internally so that source defaults, mutable container tags and remote registry changes cannot silently change what an existing installation intends to run.

The operator-facing upgrade view deliberately reduces that model to the concepts that matter during normal work: **installed**, **available**, and **selectable**. Detailed desired-state representation remains an implementation concern unless drift or migration must be diagnosed.

## Existing installations

Deployments created before explicit installation-owned version authority can record the exact already-running baseline without recreating containers:

```bash
./local-ai upgrade adopt
sudo ./local-ai upgrade adopt --yes
```

The first command is read-only. It shows the running identities and any authority keys that are still missing. The second writes only missing non-secret image/version authority keys to the protected root `.env`.

Adoption does **not** pull images, run Compose, select an upgrade or restart a service. Existing conflicting authority values fail closed rather than being overwritten.

`upgrade adopt` exists to migrate old installations to the current model. It should not become a routine step in the normal upgrade process, and fresh installations should not require it as part of ordinary maintenance.

## Internal model

Internally, the project still distinguishes installation intent, recorded successful deployment state, observed runtime state and remote availability. Those distinctions are necessary for drift detection, stale-plan protection and deterministic upgrade execution, but they are intentionally not the primary human interface.

The architecture rationale and exact ownership rules are normative in [ADR-0006](../devel-docs/adr/0006-operational-version-authority.md).
