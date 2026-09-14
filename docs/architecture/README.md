<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Architecture

[← Documentation map](../TOC.md)

The live architecture is defined by executable manifests and current repository documentation. Start with the [cross-stack architecture map](../stacks/README.md), then follow the relevant ADR, SDR and behavioural contract for the decision being investigated.

## Canonical architecture sources

- [Stack architecture](../stacks/README.md) — topology, hard dependencies and optional capabilities.
- [Architecture Decision Records](../devel-docs/adr/README.md) — why durable architectural choices were made.
- [Security Decision Records](../devel-docs/sdr/README.md) — security boundaries and least-privilege choices.
- [OpenSpec](../devel-docs/openspec/README.md) — observable behaviour and traceability to tests.
- Stack `manifest.json` files — authoritative machine-readable ownership, dependency, capability and recovery declarations.

## Research reference

[`arquitectura_hibrida_de_ia.pdf`](arquitectura_hibrida_de_ia.pdf) is retained as a research/reference document. It provides background and exploratory context, but it is **not** the source of truth for the deployed platform. If it disagrees with manifests, ADRs/SDRs or current documentation, the current executable contracts win.

Architecture documentation should not become a second configuration system: concrete container ownership and dependency facts belong in manifests and are summarized here only to make the system understandable.
