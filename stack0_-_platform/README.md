# Stack0 — Platform foundation

Mandatory base for every stack. Owns the shared Docker bridge, platform PKI/runtime foundation and manifest/environment compatibility plumbing.

```mermaid
flowchart LR
    S0[Stack0] --> Network[redlocal]
    S0 --> PKI[Platform PKI]
    S0 --> Env[Managed .env links]
    Network --> Apps[Stacks 1-7]
```

**Requires:** none.  
**Provides:** platform foundation.  
**Persistent DR state:** platform PKI.  
**Lifecycle:** prepare shared prerequisites, then verify foundation invariants.

Key files: `manifest.json`, `01-prepare.sh`, `pki.sh`, `manifests.py`, `verify.sh`.

See [../docs/installation.md](../docs/installation.md) and [../docs/dr/howto.md](../docs/dr/howto.md).
