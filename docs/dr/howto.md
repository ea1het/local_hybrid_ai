# Disaster recovery

The DR rule is simple: preserve only state whose loss would prevent a correct rebuild. A Docker volume or bind mount is not a backup target unless a manifest declares it.

`./local-ai` is the supported operator and integration boundary. DR implementation lives under `commands/recovery/`; external automation must not couple to its direct Python/script contracts.

```mermaid
flowchart LR
    Source["Known project source"] --> Recovery["Recovery"]
    Env["Protected operational .env"] --> Recovery
    PKI["Stack0 PKI"] --> Recovery
    LiteLLM["Stack3 logical DB dump"] --> Recovery
    Gitea["Stack4 native dump"] --> Recovery
    WebUI["Stack7 data archive"] --> Recovery
    Memory["Stack6 Git memory"] -. "external prerequisite" .-> Recovery
```

## Recovery policy

| Stack | Policy | Durable input |
|---|---|---|
| 0 Platform | mixed | PKI archive |
| 1 HAProxy/Web | reconstruct | none |
| 2 SearXNG/Firecrawl | reconstruct | none |
| 3 LiteLLM | mixed | logical PostgreSQL dump + original salt |
| 4 Gitea | managed | native Gitea dump |
| 5 Dockhand | reconstruct | none |
| 6 Hermes | reconstruct + external | Git-backed `MEMORY.md` + `USER.md` |
| 7 Open WebUI | mixed | `/app/backend/data` archive + secret key |

Schemas are implementation-owned by [`../../commands/recovery/`](../../commands/recovery/): [`recovery.schema.json`](../../commands/recovery/recovery.schema.json) and [`backup-set.schema.json`](../../commands/recovery/backup-set.schema.json).

## Backup

Supported operator entry point:

```bash
./local-ai backup
```

For machine consumers, use the JSON contract where supported:

```bash
./local-ai --json backup
```

A real backup validates source/runtime prerequisites, stages sensitive data privately, performs integrity checks, writes `backup.json` and `checksums.sha256`, then atomically publishes one immutable `backup-*` directory. The operational `.env` is a sensitive global artifact; its contents never belong in logs or metadata. See [ADR-0001](../devel-docs/adr/0001-backup-operational-env.md) and [SDR-0001](../devel-docs/sdr/0001-protected-operational-config-in-backups.md).

## Restore

```mermaid
flowchart LR
    CLI["./local-ai restore"] --> Validate["Validate backup + checksums"]
    Validate --> Source["Materialize recorded source"]
    Source --> Config["Restore protected config"]
    Config --> Pre["Pre-prepare archives"]
    Pre --> Prepare["PREPARE"]
    Prepare --> Managed["Managed state restore"]
    Managed --> Deploy["DEPLOY"]
    Deploy --> Ready["READY / VERIFY"]
    Ready --> External["External prerequisite convergence"]
```

Supported management forms are exposed through `./local-ai restore ...`; the underlying modules under `commands/recovery/` remain private implementation details.

Historical recovery compatibility may recognize source commits that still contain `installer/install.py` or the older root `install.py`. That is a restore-compatibility rule only; it does not make those historical paths supported management interfaces.

The generic restore path has passed a real destructive clean-target qualification for stacks 0–6. Stack7 has separately passed a current isolated archive restore from a global recovery point without modifying the live runtime. Do not repeat destructive qualification merely to recreate evidence.

## Current qualified recovery points

- Core destructive clean-target proof: `/opt/local-hybrid-ai-backups/backup-20260911T172551Z`.
- First Stack7-aware global point: `/opt/local-hybrid-ai-backups/backup-20260912T213405Z`.

Detailed evidence is in [status.md](status.md).

## Deliberately excluded

Raw PostgreSQL PGDATA, containers, images, logs, queues, caches, `.lock`, migration markers, Firecrawl transient DB/queue state, SearXNG cache, Dockhand state, Gitea runner registration, Hermes SQLite/session/cache state and sandbox contents are not DR artifacts merely because they exist.

## Remaining hardening

Encryption-at-rest, retention generations, off-host replication, external Stack6 SSH prerequisite packaging, overlap/type/schema validation hardening and resumable-recovery improvements remain active work. See [../pending.md](../pending.md).
