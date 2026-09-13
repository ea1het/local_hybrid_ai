# Documentation

The repository keeps executable contracts close to the code and longer operational material here.

```mermaid
flowchart LR
    Root["README.md"] --> Stacks["stack README files"]
    Root --> Install["docs/installation.md"]
    Root --> Upgrade["docs/upgrade-policy.md"]
    Root --> DR["docs/dr/"]
    Root --> Dev["docs/devel-docs/"]
    Dev --> ADR["adr/"]
    Dev --> SDR["sdr/"]
    Dev --> Spec["openspec/"]
```

## What lives where

- `stack*/README.md`: short contract for one stack: purpose, dependencies, owned runtime, persistence and lifecycle.
- `installation.md`: operator installation and guarded-upgrade flow.
- `upgrade-policy.md`: registry availability versus compatibility policy, installation overrides and policy CLI.
- `dr/`: disaster-recovery design, evidence and operating procedures.
- `architecture/`: architecture reference material.
- `configuration/`: configuration and secret-handling documentation.
- `a2aknowledge.md`: continuity/handoff context for AI-assisted work.
- `pending.md`: active backlog and closed qualification evidence.
- `devel-docs/adr/`: architectural decisions.
- `devel-docs/sdr/`: security decisions and accepted risk.
- `devel-docs/openspec/`: executable-oriented behaviour specification linked to tests.
- `devel-docs/testing.md`: repository validation and qualification guidance.

Historical verbose per-stack Spanish documents are retained under `stacks/legacy/`; the canonical stack documentation is each stack's `README.md`.
