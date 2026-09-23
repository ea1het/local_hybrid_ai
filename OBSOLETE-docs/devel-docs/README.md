<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Developer documentation

[← Documentation map](../TOC.md)

This area contains design decisions, executable-oriented specifications, security rationale, testing strategy and maintenance guidance for contributors and maintainers. It is intentionally separate from the operator contract in [`../user-docs/`](../user-docs/README.md).

## Index

- [Documentation maintenance standard](documentation.md)
- [Architecture Decision Records](adr/README.md)
- [Security Decision Records](sdr/README.md)
- [OpenSpec / Gherkin behavioural contracts](openspec/README.md)
- [OpenSpec traceability](openspec/traceability.md)
- [Testing strategy and qualification](testing.md)
- [Upgrade executor qualification](upgrade-qualification.md)
- [Management-plane architecture](../architecture/management-plane.md)
- [Architecture reference](../architecture/README.md)
- [Cross-stack architecture](../stacks/README.md)
- [AI-assisted maintenance context](../a2aknowledge.md)
- [Current backlog](../pending.md)

Source-adjacent `README.md` files remain next to their code because they are local implementation entry points, not an alternative long-form documentation tree. Long-form project documentation belongs under `docs/`.

Architecture rationale belongs in ADRs, security rationale in SDRs, observable behaviour in OpenSpec/Gherkin, and verification rules in tests and qualification documentation. Historical implementation milestones and conversation-derived closeout notes are not canonical documentation; durable conclusions belong in the appropriate document above, while chronology remains available in Git history.
