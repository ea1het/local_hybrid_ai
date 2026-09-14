<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# ADR-0007 — Manifest-owned component inventory

- Status: Accepted
- Date: 2026-09-15

## Context

Stack manifests already define dependency, capability and resource ownership, while Docker Compose defines the concrete services implementing each stack. Upgrade management had accumulated a separate central component catalog. That duplicated stack topology and created a long-term failure mode: a structural stack change could update its manifest and Compose file while leaving the CLI's central catalog stale.

Structural changes are expected over the lifetime of the project. A stack may add or remove a sidecar, replace a locally managed component, rename a service, or introduce a new versioned component. The management boundary must not require a second manually synchronized inventory to understand such changes.

Not every owned container has the same lifecycle. Some are externally versioned applications, some are project-managed local images, and some are fixed helpers that should not appear in the normal upgrade workflow.

## Decision

Each stack `manifest.json` is the semantic source of truth for its components. Every owned `container:*` resource must have exactly one entry in `components[]` describing its operational meaning.

The supported management types are:

- `versioned` — externally versioned software eligible for version inventory and, when qualified, upgrade execution;
- `local` — project-managed/reconstructable component that is not upgraded by registry discovery;
- `helper` — internal support container whose lifecycle is part of the stack rather than an independent operator upgrade target;
- `platform` — non-container or non-versioned platform component represented for management completeness.

A component may include an `upgrade` block when it belongs in the operator upgrade inventory. That block carries compatibility policy, availability semantics, executor qualification state and any deterministic mutation recipe. Components without an `upgrade` block remain part of stack topology but are intentionally absent from normal version maintenance.

`commands/component_inventory.py` compiles and validates the component topology from the manifests returned by the existing Stack0 manifest resolver. It verifies that every owned container is classified, that a container is not classified twice, and that declared Compose services exist.

There is no hand-maintained central upgrade component catalog. `commands/upgrade.py` consumes a compatibility-shaped view compiled from manifests on every invocation. The compiled view is an implementation adapter, not another authority.

## Rescan and source changes

`./local-ai inventory rescan` validates the current manifest/Compose topology, calculates a source fingerprint and records a derived snapshot under the installation runtime platform area. The snapshot is used only to report structural differences between rescans (`added`, `removed`, `changed`).

The snapshot is not used as management authority. `status` and `upgrade` compile the current manifests directly, so forgetting to run rescan after `git pull` cannot leave the CLI operating from stale topology metadata.

Rescan may update its own derived snapshot, but it must not prepare, deploy, recreate or remove containers, mutate `.env`, select upgrades or contact registries. A removed component is reported as removed; it is never interpreted automatically as consent to delete an old runtime resource. Migration or replacement semantics require an explicit stack-owned migration contract.

## Compose relationship

Manifests describe semantic ownership and management meaning. Compose describes implementation binding. The inventory compiler checks the relationship but does not infer management type from image syntax, tags or service names. A locally managed component can therefore use an externally based pinned image while still remaining outside registry-driven upgrade semantics.

## Consequences

A structural stack change is self-describing when its manifest and Compose change together. Missing classification or a stale service binding fails explicitly during inventory compilation instead of silently producing an incomplete CLI view.

Adding a container now requires declaring its component semantics in the owning manifest. Removing or renaming a container requires updating both ownership and component metadata. Upgrade policy/executor metadata moves with the component into the stack that owns it.

The management CLI remains decoupled from individual stack topology. New component types or migration semantics can evolve through the manifest contract without reintroducing a central list of stack services.
