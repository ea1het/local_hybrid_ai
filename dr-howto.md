# Disaster recovery how-to

This document defines the disaster-recovery model and recovery-engine contract for `local_hybrid_ai`.

The design goal is deliberately small: preserve only state whose loss would materially prevent recovery. Everything else must be reconstructable from Git, protected configuration and fresh stack deployment.

> **Current implementation status:** manifest recovery contracts, read-only planning/preflight, the execution filesystem contract and the first real Stack0 `archive` backup adapter are implemented. Stack0 `platform-pki` backup creation has been validated on the real host. `dr_archive_restore.py` now provides an isolated restore-verification milestone that never writes to the live runtime path. PostgreSQL, Gitea, multi-stack real backup and live restore remain disabled.

## 1. Recovery principles

The platform distinguishes physical persistence from disaster-recovery value. A Docker volume, bind mount, database file or runtime directory is not automatically a backup target.

The intended recovery inputs are:

```text
Git source at a known commit/tag
+ protected operational .env
+ Stack0 platform PKI
+ Stack3 LiteLLM logical database dump
+ Stack4 Gitea application-native dump
```

Everything else should be reconstructable or externalized.

Do not back up live PostgreSQL PGDATA as the normal DR mechanism. Use logical/application-aware recovery artifacts. Do not encode Docker-internal paths such as `/var/lib/docker/overlay2/...` or named-volume mountpoints as architectural recovery contracts.

## 2. Normalized manifest contract

Each stack manifest contains a `recovery` object validated by [`recovery.schema.json`](recovery.schema.json):

```text
recovery
├── contract     REQUIRED in every stack
└── resources    OPTIONAL; present only when recovery resources exist
```

The mandatory contract is:

```json
{
  "recovery": {
    "contract": {
      "schema_version": 1,
      "mode": "reconstructable"
    }
  }
}
```

Valid modes are `reconstructable`, `managed`, and `mixed`. Resource classes are `persistent-data`, `persistent-identity`, and `externalized`. Version 1 strategies are `archive`, `postgres-custom-dump`, `gitea-native-dump`, `external-config`, and `git`.

## 3. Restore phases

Managed filesystem/application resources may declare `pre-prepare`, `post-prepare-pre-deploy`, or `post-deploy`. The contract deliberately avoids arbitrary workflow expressions; recovery sequencing remains a small platform lifecycle.

## 4. Stack-by-stack decision

| Stack | Recovery mode | Durable recovery target | Decision |
|---|---|---|---|
| Stack0 Platform | `mixed` | platform PKI | **BACKUP** |
| Stack1 HAProxy/Web | `reconstructable` | none | **RECONSTRUCT** |
| Stack2 SearXNG/Firecrawl | `reconstructable` | none | **RECONSTRUCT** |
| Stack3 LiteLLM | `mixed` | LiteLLM DB + original `LITELLM_SALT_KEY` | **BACKUP + REQUIRE** |
| Stack4 Gitea | `managed` | complete logical/application state | **BACKUP** |
| Stack5 Dockhand | `reconstructable` | none | **RECONSTRUCT** |
| Stack6 Hermes | `reconstructable` | knowledge/memory externalized to Git | **EXTERNAL** |

Stack0 PKI survives rebuild and is restored `pre-prepare`. Stack2 and Stack5 are disposable. LiteLLM uses a logical PostgreSQL dump rather than PGDATA and requires the original `LITELLM_SALT_KEY`. Gitea uses its native application dump. Hermes runtime remains disposable only when all operator-valued knowledge is externalized to Git/Gitea; `SOUL.md` and similar mutable runtime-only knowledge remain a migration gap until that externalization is complete.

## 5. Protected configuration

The operational `.env` is a protected recovery prerequisite outside Git. Recovery tooling must never print it, commit it, or place secret values into unprotected metadata.

## 6. Planner and dry-run

```bash
python3 dr.py plan all
python3 dr.py backup all --dry-run
```

Planning classifies resources as `BACKUP`, `REQUIRE`, `EXTERNAL`, or `RECONSTRUCT`. Backup dry-run performs read-only destination and runtime/source preflight. Destination precedence is:

```text
--destination
> DR_BACKUP_ROOT
> /opt/local-hybrid-ai-backups
```

The runtime/source preflight verifies archive paths, protected configuration presence, PostgreSQL source readiness, Gitea version/dump command availability and externalized Git declarations without exposing protected values.

## 7. Execution filesystem contract

[`dr_filesystem.py`](dr_filesystem.py) prepares the selected backup root with mode `0700`, validates ownership and exercises the same-parent atomic publication primitive using a transient private probe. Existing non-conforming roots fail closed and are never silently chmod/chowned.

Validated host destination:

```text
/opt/local-hybrid-ai-backups/   owner=root  mode=0700
```

## 8. First real adapter: Stack0 archive

[`dr_archive.py`](dr_archive.py) currently enables real execution only when the dependency plan is exactly Stack0:

```bash
python3 dr_archive.py 0 --destination /opt/local-hybrid-ai-backups
```

It creates a private temporary sibling directory, archives the bounded Stack0 PKI source, calculates SHA-256 and size, writes and validates `backup.json`, writes `checksums.sha256`, fsyncs the set and publishes it atomically using no-replace semantics. PostgreSQL, Gitea, multi-stack execution and generic `dr.py backup` remain blocked.

The first real host backup was successfully published as a completed Stack0 backup set. The archive contained only the bounded relative `pki/` tree; metadata/checksums validated; the original PKI fingerprint was unchanged; no hidden temporary directories remained.

## 9. Isolated archive restore verification

[`dr_archive_restore.py`](dr_archive_restore.py) is deliberately a **verification harness**, not a live restore command. It accepts a completed Stack0 backup-set directory, validates metadata and integrity, safely extracts `platform-pki.tar` into a newly-created private temporary directory under the system temporary area, optionally compares the restored tree with the current source tree, and deletes the temporary restore tree before returning.

Example for the validated host backup:

```bash
python3 dr_archive_restore.py \
  /opt/local-hybrid-ai-backups/backup-20260910T162652Z \
  --compare-source /opt/docker/runtime/service_-_platform/pki
```

The verifier rejects absolute paths, `..` traversal, members outside the expected `pki` root, unsupported TAR member types and unsafe symlink targets. It validates the archive hash/size against `backup.json` and validates both the artifact and `backup.json` entries in `checksums.sha256` before extraction.

Comparison deliberately ignores inode numbers because a restored filesystem tree must receive new inodes. It compares relative path, type, restored mode, file SHA-256 and symlink target. A successful comparison proves that the backup can reproduce the logical PKI tree without touching the active runtime source.

The verifier never writes to:

```text
/opt/docker/runtime/service_-_platform/pki
```

and reports `live_runtime_modified: false` in JSON output.

## 10. Completed backup-set layout

A completed set uses:

```text
/opt/local-hybrid-ai-backups/
└── backup-YYYYMMDDTHHMMSSZ/
    ├── backup.json
    ├── checksums.sha256
    └── artifacts/
        └── stackN/
            └── resource artifact
```

[`backup-set.schema.json`](backup-set.schema.json) defines completed metadata. `backup.json` records source commit, requested/resolved stacks, artifact identity/path, SHA-256, size and prerequisite classifications; secret values do not belong in metadata.

## 11. What is intentionally excluded

The DR design excludes Firecrawl PostgreSQL/Redis/RabbitMQ state, SearXNG runtime/cache, physical PGDATA copies as the normal restore mechanism, Dockhand state, Hermes operational caches/databases/sandbox state, Gitea runner registration state, Docker containers/images/overlay internals, `.lock`, temporary files and migration markers.

## 12. Remaining engine milestones

```text
destination/runtime preflight            DONE
execution filesystem contract            DONE
Stack0 archive backup                     DONE + host validated
Stack0 isolated archive restore verifier  IMPLEMENTED; host validation NEXT
-> Stack3 postgres-custom-dump
   exact credential/consistency contract
   logical dump generation
   isolated restore test
-> Stack4 gitea-native-dump
   exact deployed-version dump contract
   isolated restore test
-> generic multi-stack backup-set execution
-> restore orchestration by declared restore phase
-> clean-environment full rebuild proof
```

No recovery engine is complete until it proves both artifact creation and restoration into a clean deployment.
