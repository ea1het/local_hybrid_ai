<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Documentation maintenance standard

[Documentation TOC](../TOC.md) · [Developer documentation](README.md)

Documentation is part of the repository contract. It must explain ownership, boundaries and observable behaviour without turning private implementation details into supported APIs.

## Navigation

`docs/TOC.md` is the canonical documentation map. Every directory under `docs/` has a `README.md` that:

1. links back to the canonical TOC;
2. explains the purpose of that directory;
3. links to the documents and relevant sibling areas.

Long-form project documentation belongs under `docs/`. Source-adjacent `README.md` files remain beside each stack because they are the local implementation contract for that stack.

## Python module documentation

Every Python file has a module docstring before imports (after a shebang when present). A useful module docstring answers:

- what responsibility the module owns;
- which architectural or security boundary it implements;
- what important behaviour it deliberately does **not** own;
- whether it mutates state or is read-only when that distinction matters.

Do not use empty descriptions such as “utilities” or “tests for module X”. Prefer the contract being protected.

## Test documentation

Every test module has a module docstring. It should identify:

- the subsystem or behavioural contract under test;
- the regression class the tests are intended to prevent;
- important scope boundaries, for example deterministic injection versus live registry qualification.

Individual test names remain behaviour-oriented. Additional per-test comments are needed only when the reason for a fixture, mock or negative assertion is not self-evident.

## Gherkin / OpenSpec

Each `.feature` starts with a short scope paragraph immediately after `Feature:`. The paragraph explains why the feature exists and which architectural boundary it describes.

Tagged scenarios describe durable observable behaviour, not implementation recipes. A good scenario includes context, trigger, expected result and negative boundary. Every tag must have evidence in `openspec/traceability.md`.

Use an ADR for architectural decisions, an SDR for security decisions/risk treatment, and OpenSpec for observable behaviour. Link them when one decision has consequences in more than one layer.

## Mermaid

Use GitHub-supported Mermaid fenced blocks and keep diagrams intentionally small. Prefer `flowchart LR`, `flowchart TB` or `flowchart TD` for architecture/lifecycle diagrams. Node identifiers should be simple alphanumeric identifiers; human labels belong inside node labels.

A diagram should communicate one relationship model. Split a diagram instead of adding enough nodes/edges that GitHub rendering becomes harder to read than prose.

Use solid arrows for required/request-flow relationships and dotted arrows for optional/publication relationships when that convention improves comprehension; explain the distinction in nearby prose.

## Markdown tables

Tables are appropriate for compact categorical data. Avoid wide tables containing long paths, test names, commands or prose because GitHub hides columns on normal-width screens. Prefer:

- two-column tables for short mappings;
- headings plus short paragraphs for traceability/evidence;
- bullets for long identifiers or multiple independent facts.

If the reader must horizontally scroll to discover the most important field, the table should be redesigned.

## Evidence and verification language

Documentation distinguishes:

- **implemented** — present in source;
- **automated evidence** — protected by repository tests;
- **runtime-qualified** — observed on the actual m92p installation or another named qualification environment;
- **proposed** — not yet implemented/qualified.

Do not describe unit/contract tests as live qualification and do not claim runtime success without recorded evidence.

## Automated structural checks

`tests/test_documentation_contract.py` protects minimum structure: module docstrings, docs-directory README coverage, TOC backlinks, Gherkin scope text and supported Mermaid block declarations. It complements human review; passing the structural test is necessary but does not prove documentation quality.
