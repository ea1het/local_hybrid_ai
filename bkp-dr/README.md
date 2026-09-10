# Backup & Disaster Recovery

This directory is the single home for the project's backup/DR implementation, schemas, tests and operational documentation.

## Start here

- [`STATUS.md`](STATUS.md): verified state, real backup evidence and exact handoff to the next AI agent.
- [`dr-howto.md`](dr-howto.md): operational recovery contract.
- [`recovery.schema.json`](recovery.schema.json): normalized per-stack recovery declaration.
- [`backup-set.schema.json`](backup-set.schema.json): completed backup-set metadata contract.
- [`dr-gitea.md`](dr-gitea.md): Gitea native consistent-backup/restore notes.
- [`dr-postgres.md`](dr-postgres.md): PostgreSQL logical-backup verification.
- [`dr-archive.md`](dr-archive.md): archive strategy.
- [`dr-filesystem.md`](dr-filesystem.md): backup destination/filesystem contract.

## Code

The DR engine and adapters are colocated here: `dr.py`, `dr_archive.py`, `dr_filesystem.py`, `dr_postgres_verify.py`, Stack3 and Stack4 adapters/verifiers. DR tests live under [`tests/`](tests/).

Because the implementation was moved from repository root without changing its project-root assumptions, compatibility symlinks in this directory point back to the root `.env` and stack directories. They contain no secret data; `.env` itself remains ignored and protected. A future cleanup may replace this compatibility layer with an explicit project-root resolver; track that in [`../pending.md`](../pending.md).

## Verified DR coverage

```mermaid
flowchart LR
  SRC[Git source at known commit] --> R[Rebuild]
  ENV[Protected operational .env] --> R
  PKI[Stack0 PKI archive] --> R
  LDB[Stack3 LiteLLM logical dump] --> R
  GS[Stack4 consistent Gitea native dump] --> R
  R --> S1[Stack1 reconstruct]
  R --> S2[Stack2 reconstruct]
  R --> S5[Stack5 reconstruct]
  R --> S6[Stack6 reconstruct after knowledge externalization]
```

Verified on the reference host before this documentation/reorganization change:

- Stack0 `platform-pki`: real backup + isolated restore verification passed.
- Stack3 `litellm-database`: real custom-format dump + temporary-database restore verification passed.
- Stack4 `gitea-state`: real **controlled-offline** native backup + isolated SQLite/repository restore verification passed.
- Stack4 consistent set: `/opt/local-hybrid-ai-backups/backup-20260910T224812Z`; Gitea was stopped briefly, restarted healthy, no helper remained, checksums passed; restore imported 116 SQLite tables (38 non-empty) and `git fsck` passed for 8/8 repositories.
- Stack1, Stack2 and Stack5 are reconstructable by policy.
- Stack3 `LITELLM_SALT_KEY` is an external protected `.env` prerequisite, not copied into backup sets.
- Stack6 is intended to be reconstructable, but operator-valued knowledge still present only in runtime (notably `SOUL.md` if still runtime-only) must be externalized before generic `backup all` can be considered complete.

## Safety

Never use DR work as a reason to run `docker compose down -v`, prune Docker broadly, delete `/opt/docker/runtime`, overwrite `.env`, rotate persistent identities, or copy raw PostgreSQL PGDATA as the recovery mechanism.
