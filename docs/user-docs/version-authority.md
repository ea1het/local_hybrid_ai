<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Component version authority

[← User documentation](README.md) · [Upgrade guide](upgrade.md) · [ADR-0006](../devel-docs/adr/0006-operational-version-authority.md)

This page provides migration and advanced background. It is **not** the normal operator upgrade workflow. Day-to-day maintenance begins with [`./local-ai upgrade`](upgrade.md).

Local Hybrid AI keeps an installation-owned version authority internally so that source defaults, mutable container tags and remote registry changes cannot silently change what an existing installation intends to run.

The operator-facing upgrade view deliberately reduces that model to the concepts that matter during normal work: **installed**, **available**, and **selectable**. Detailed desired-state representation remains an implementation concern unless drift or migration must be diagnosed.

## Catalog boundary

The upgrade catalog contains application components whose release identity is meaningful to an operator, plus project-managed local components where showing `local` makes their lifecycle explicit. It is not a mechanical list of every image referenced by Compose.

Fixed implementation/support images that are part of a stack's internal construction remain source-controlled dependencies outside the operator upgrade catalog when they do not have an independent application lifecycle. For example, Stack1's `busybox:1.38.0` static-web helper is an exact source pin: changing it is a Stack1 source change reviewed and tested with that stack, not an independent `local-ai upgrade` target. Such support images remain exact rather than becoming moving registry channels.

Project-built components such as the Gitea runner and Hermes sandbox are represented as `local` rather than being discovered from a registry. Their runtime health belongs to stack status, while their construction identity belongs to project source.

## Existing installations

Deployments created before explicit installation-owned version authority can record the exact already-running baseline without recreating containers:

```bash
./local-ai upgrade adopt
sudo ./local-ai upgrade adopt --yes
```

The first command is read-only. It shows the running identities and any authority keys that are still missing. The second writes only missing non-secret image/version authority keys to the protected root `.env`.

Adoption does **not** pull images, run Compose, select an upgrade or restart a service. Existing conflicting authority values fail closed rather than being overwritten.

`upgrade adopt` exists to migrate old installations to the current model. It is not a routine step in the normal upgrade process, and fresh installations do not require it as part of ordinary maintenance.

## Internal model

Internally, the project still distinguishes installation intent, recorded successful deployment state, observed runtime state and remote availability. Those distinctions are necessary for drift detection, stale-plan protection and deterministic upgrade execution, but they are intentionally not the primary human interface.

The architecture rationale and exact ownership rules are normative in [ADR-0006](../devel-docs/adr/0006-operational-version-authority.md).
