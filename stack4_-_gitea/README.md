# Stack4 — Gitea + Runner

[Home](../README.md) · [Install](../INSTALLATION.md) · [DR](../bkp-dr/README.md) · [Gitea DR](../bkp-dr/dr-gitea.md)

Stack4 owns Gitea and its Actions runner. It requires Stack0. `git.remote` is an optional capability consumed by Stack6; the runner is reconstructable and may be re-registered.

```mermaid
flowchart LR
  S0[Stack0] --> S4[Stack4 Gitea]
  S4 --> G[Git repositories + app state]
  S4 --> R[Actions runner]
  S4 -. git.remote .-> S6[Stack6 Hermes]
```

DR classification: **managed** for `gitea-state`. Definitive backup policy is a brief controlled stop of only Gitea, native Gitea dump in the same rootless image/user/path context, restart + health verification, then artifact validation and atomic publication. The runner token/runtime identity is not a core DR artifact.

Real controlled-offline backup and isolated restore verification have passed: SQLite import succeeded and all discovered repositories passed `git fsck`. See [`../bkp-dr/STATUS.md`](../bkp-dr/STATUS.md).
