<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Documentation maintenance standard

[Documentation TOC](../TOC.md) · [Developer documentation](README.md) · [Management-plane architecture](../architecture/management-plane.md)

Documentation is part of the repository contract. It explains ownership, boundaries and observable behaviour without turning private implementation details into supported APIs.

## Audience and writing voice

Repository documentation is written primarily for human operators, contributors and maintainers. Agent-oriented documents are exceptional and explicitly identified as such. Every document must stand on its own without requiring access to private discussions, a particular maintainer's workstation or one deployment's operational history.

Human-facing prose uses third-person, role-oriented language. An operator, administrator, maintainer, contributor, component or subsystem is named explicitly when that role matters. Direct second-person instructions are avoided. Literal commands, code, configuration keys, Gherkin steps, error text and quoted interface contracts remain exact.

For example, an operator guide states that "the operator runs `./local-ai status`" rather than "run `./local-ai status`". A safety rule states that "an administrator must not treat registry discovery as consent" rather than addressing the reader directly.

Public documentation must therefore:

- describe roles, contracts and representative environments rather than individual people or privately named machines;
- avoid publishing local hostnames, usernames, home-directory paths, internal DNS names, IP addresses, backup-set identifiers, temporary artifact names or deployment-specific user/content counts unless the exact value is an intentional public default or interface contract;
- prefer symbolic names such as `STACKS_ROOT`, `BASE_PATH`, "operator host" or "qualification environment" when a concrete local value is not part of the product contract;
- separate durable system behaviour from implementation chronology: architectural decisions belong in ADRs, security decisions in SDRs, observable behaviour in OpenSpec, active work in `pending.md`, and detailed historical chronology in Git and pull-request history;
- avoid conversation-derived closeout documents once their durable conclusions have been incorporated into canonical documentation.

## Navigation contract

`docs/TOC.md` is the canonical documentation map and contains the high-level documentation architecture. Every documentation area must be reachable from that map, directly or through an indexed parent. A normal navigation chain is `README → TOC → area README → document`, with documents linking back to the TOC or their indexed parent.

Every directory under `docs/` has a `README.md` that:

1. links back to the canonical TOC;
2. explains the purpose of that directory;
3. links to the documents and relevant sibling areas.

Source-adjacent stack `README.md` files remain beside their code because they are local implementation contracts. They are indexed from `docs/stacks/README.md` and from the canonical TOC. Test layout and strategy are documented in [developer testing](testing.md) rather than in a source-adjacent `tests/README.md`, because there is no root `tests/` package: every test lives under the `tests/<package>/` package it protects.

Long-form project documentation belongs under `docs/` unless proximity to the source is itself part of the document's purpose.

## Source of truth and document types

Documentation does not become a second configuration system. Executable manifests and supported CLI contracts remain authoritative for machine-readable ownership and behaviour.

- Architecture documentation explains responsibility and topology.
- ADRs preserve architectural decisions and their historical rationale; they are not rewritten merely because an internal module moved.
- SDRs preserve security decisions and risk treatment.
- OpenSpec/Gherkin describes current observable behaviour and therefore changes when behaviour changes.
- Traceability connects current behaviour to implementation and evidence and therefore changes when implementation boundaries move.
- Operator documentation describes supported public interfaces, not private modules or stack scripts.
- `pending.md` contains only work that is still genuinely pending.
- Agent-oriented continuity material is clearly marked and is not treated as an operator guide.

## Python module documentation

Every Python file has a module docstring before imports (after a shebang when present). A useful module docstring answers:

- what responsibility the module owns;
- which architectural or security boundary it implements;
- what important behaviour it deliberately does **not** own;
- whether it mutates state or is read-only when that distinction matters.

Descriptions such as “utilities” or “tests for module X” are avoided in favor of the contract being protected.

## Test documentation

Every test module has a module docstring. It identifies:

- the subsystem or behavioural contract under test;
- the regression class the tests are intended to prevent;
- important scope boundaries, for example deterministic injection versus runtime registry qualification.

Individual test names remain behaviour-oriented. Additional per-test comments are needed only when the reason for a fixture, mock or negative assertion is not self-evident.

## Gherkin / OpenSpec

Each `.feature` starts with a short scope paragraph immediately after `Feature:`. The paragraph explains why the feature exists and which architectural boundary it describes.

Tagged scenarios describe durable observable behaviour, not implementation recipes. A scenario includes context, trigger, expected result and negative boundary where relevant. Every tag has evidence in `openspec/traceability.md`.

An ADR records an architectural decision, an SDR records a security decision, and OpenSpec records observable behaviour. Cross-links connect the layers without duplicating their content.

## Mermaid

GitHub-supported Mermaid fenced blocks are preferred when topology, sequencing, state transitions or responsibility boundaries would otherwise require substantial prose. Diagrams remain intentionally scoped to one concern.

`flowchart LR`, `flowchart TB` or `flowchart TD` suit architecture and lifecycle relationships. `sequenceDiagram` suits guarded operations such as upgrade or recovery. Node identifiers remain simple; human labels belong inside node labels.

Solid arrows represent required/request-flow relationships and dotted arrows represent optional/publication relationships when that convention improves comprehension. Nearby prose explains any non-obvious convention.

## Markdown tables

Tables are appropriate for compact categorical data. Wide tables containing long paths, test names, commands or prose are avoided because GitHub hides columns on normal-width screens. Two-column mappings, headings with short paragraphs, or bullets are preferred when they preserve readability.

## Evidence and verification language

Documentation distinguishes:

- **implemented** — present in source;
- **automated evidence** — protected by repository tests;
- **runtime-qualified** — observed in a recorded representative deployment or qualification environment;
- **proposed** — not yet implemented or qualified.

Automated unit or contract tests are not live qualification. Runtime success is not claimed without recorded evidence. Public documentation summarizes the relevant outcome without exposing environment-specific identifiers that are not part of the contract.

## Automated structural checks

`tests/repository/test_documentation_contract.py` protects minimum structure: module docstrings, docs-directory README coverage, TOC backlinks, relative-link resolution, Gherkin scope text, supported Mermaid block declarations and common deployment-local residue. It complements human review; passing the structural test is necessary but does not prove documentation quality or semantic agreement with current source.
