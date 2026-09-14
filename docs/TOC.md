<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Documentation map

This is the canonical table of contents for Local Hybrid AI. Every documentation section links back here, and folder `README.md` files act as local indexes rather than independent documentation islands.

[← Project README](../README.md)

## Start here

- [Project overview](../README.md) — what the platform is, why it is local-first, stack relationships and supported management boundary.
- [Installation and lifecycle](installation.md) — PREPARE → DEPLOY → READY → RECONCILE → VERIFY.
- [Operator CLI](user-docs/cli.md) — supported `./local-ai` commands and JSON contracts.
- [Upgrade workflow](user-docs/upgrade.md) — installed/available/selectable workflow, selection, guarded apply and failure handling.
- [Administrator-forced upgrades](user-docs/forced-upgrades.md) — explicit risk acceptance for known but not yet qualified mutation paths.
- [Component version authority](user-docs/version-authority.md) — installation-owned version intent and migration from older deployments.
- [Configuration and secrets](configuration/README.md) — protected `.env`, generated secrets and ownership rules.
- [Disaster recovery](dr/README.md) — backup/restore model, operating procedure and qualification status.
- [Upgrade compatibility policy](upgrade-policy.md) — compatibility boundaries independent from executor selectability.

## Architecture

- [Architecture index](architecture/README.md)
- [Stack architecture](stacks/README.md) — responsibilities, hard dependencies, optional capabilities and cross-stack data/control flows.
- [Architecture Decision Records](devel-docs/adr/README.md) — durable architectural choices and their consequences.
- [Security Decision Records](devel-docs/sdr/README.md) — security boundaries, least privilege and accepted constraints.
- [Behavioural specifications](devel-docs/openspec/README.md) — Gherkin/OpenSpec contracts linked to implementation and tests.
- [Traceability](devel-docs/openspec/traceability.md) — contract → implementation → test mapping.

## Operations

- [User documentation](user-docs/README.md)
- [Upgrade workflow](user-docs/upgrade.md)
- [Administrator-forced upgrades](user-docs/forced-upgrades.md)
- [Component version authority](user-docs/version-authority.md)
- [Integrations](user-docs/integrations/README.md)
- [Disaster recovery](dr/README.md)
- [Active backlog](pending.md)

## Development

- [Developer documentation](devel-docs/README.md)
- [Documentation maintenance standard](devel-docs/documentation.md)
- [Testing and qualification](devel-docs/testing.md)
- [Upgrade executor qualification](devel-docs/upgrade-qualification.md)
- [ADR index](devel-docs/adr/README.md)
- [SDR index](devel-docs/sdr/README.md)
- [OpenSpec index](devel-docs/openspec/README.md)
- [Feature contracts](devel-docs/openspec/features/README.md)
- [Per-stack contracts](devel-docs/openspec/stacks/README.md)
- [AI-assisted continuity contract](a2aknowledge.md)

## Documentation rules

1. `README.md` at repository root explains the system to a new reader; it is not a file inventory.
2. `docs/TOC.md` is the canonical navigation map.
3. Every folder below `docs/` has a `README.md` that links to this TOC and indexes the documents it owns.
4. Stack implementation READMEs explain the local stack contract; `docs/stacks/README.md` explains relationships across stacks.
5. ADRs explain architectural decisions; SDRs explain security decisions; Gherkin/OpenSpec describes externally observable behaviour. These documents cross-link instead of duplicating one another.
6. Wide tables are avoided. Prefer compact tables with short cells, followed by prose for detail.
7. Mermaid diagrams use GitHub-supported syntax and model one concern per diagram. Cross-stack diagrams identify required dependencies separately from optional capability relationships.
8. Historical documents are retained only when they contain knowledge not represented by current canonical documentation. Once migrated, obsolete legacy copies are deleted.
9. Python modules and tests start with module-level documentation that explains responsibility, behavioural scope and important negative boundaries.

The complete maintenance rules are defined in [the documentation standard](devel-docs/documentation.md).
