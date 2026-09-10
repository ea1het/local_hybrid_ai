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

DR classification: **managed** for `gitea-state`. Definitive backup policy is a brief controlled stop of only Gitea, native Gitea dump using the **execution context discovered from the deployed container**, restart + health verification, then artifact validation and atomic publication. Rootless vs. rootful is an implementation property of the current Gitea deployment, not part of the DR contract.

Before stopping Gitea, the adapter discovers the deployed image, configured container user (or image-default user), working path, `GITEA_CUSTOM` and active `app.ini` path. The helper uses the same image and mounted Gitea volumes and reproduces that context. It fails closed if the active configuration path cannot be identified safely; it must never fall back to historical rootless constants.

The runner token/runtime identity is not a core DR artifact. Real controlled-offline backup and isolated restore verification have passed for the current rootless deployment: SQLite import succeeded and all discovered repositories passed `git fsck`. Any future change of Gitea image/layout or rootless/rootful mode must re-run the real backup + isolated restore qualification. See [`../bkp-dr/STATUS.md`](../bkp-dr/STATUS.md).
