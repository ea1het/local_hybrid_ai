# Stack4 — Gitea + Runner

Owns the local Git service and Actions runner.

```mermaid
flowchart LR
    Users --> Gitea
    Gitea --> Repos[(Repositories)]
    Runner[Actions runner] --> Gitea
    HermesMemory[Stack6 memory sync] -. optional git.remote .-> Gitea
```

**Requires:** Stack0.  
**Provides:** optional `git.remote`.  
**Persistence:** Gitea repositories and application state.  
**DR:** controlled Gitea-native dump; repositories are verified with `git fsck`. Runner registration is reconstructable.

See [../docs/dr/gitea.md](../docs/dr/gitea.md).
