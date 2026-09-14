<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Per-stack behavioural contracts

[← OpenSpec](../README.md) · [Documentation map](../../../TOC.md)

Each feature file captures externally relevant invariants for one atomic stack. Cross-stack dependency and capability semantics are documented in [the stack architecture](../../../stacks/README.md); implementation ownership is declared by each stack `manifest.json`.

- [Stack0 — Platform](stack0.feature)
- [Stack1 — HAProxy/Web](stack1.feature)
- [Stack2 — SearXNG/Firecrawl](stack2.feature)
- [Stack3 — LiteLLM](stack3.feature)
- [Stack4 — Gitea](stack4.feature)
- [Stack5 — Dockhand](stack5.feature)
- [Stack6 — Hermes](stack6.feature)
- [Stack7 — Open WebUI](stack7.feature)

When a stack consumes a capability from another stack, the scenario should distinguish **required dependency** from **optional capability**. Optional providers must not be rewritten as hard installation dependencies merely because a feature becomes available when they are READY.
