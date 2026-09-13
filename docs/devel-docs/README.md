# Developer documentation

[← Documentation map](../TOC.md)

This area contains design decisions, executable-oriented specifications, security rationale, testing strategy and maintenance context. It is intentionally separate from the operator contract in [`../user-docs/`](../user-docs/README.md).

## Index

- [Architecture Decision Records](adr/README.md)
- [Security Decision Records](sdr/README.md)
- [OpenSpec / Gherkin behavioural contracts](openspec/README.md)
- [Testing strategy and qualification](testing.md)
- [Architecture reference](../architecture/README.md)
- [Cross-stack architecture](../stacks/README.md)
- [AI-assisted continuity context](../a2aknowledge.md)
- [Current backlog and qualification evidence](../pending.md)
- [Point 10 closeout record](point10-closeout.md)

Source-adjacent `README.md` files remain next to their code because they are local implementation entry points, not an alternative long-form documentation tree. Long-form project documentation belongs under `docs/`.

Architecture rationale belongs in ADRs, security rationale in SDRs, observable behaviour in OpenSpec/Gherkin and proof in tests/qualification. Cross-links should connect those layers instead of repeating the same decision in four places.
