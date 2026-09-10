# Disaster recovery how-to

This document defines the disaster-recovery model and recovery-engine contract for `local_hybrid_ai`.

The design goal is deliberately small: preserve only state whose loss would materially prevent recovery. Everything else must be reconstructable from Git, protected configuration and fresh stack deployment.

## 1. Recovery principles

A Docker volume, bind mount, database file or runtime directory is not automatically a backup target. Recovery policy is declared in stack manifests and verified with bounded strategy-specific tooling.

The intended recovery inputs are:

```text
Git source at a known commit/tag
+ protected operational .env
+ Stack0 platform PKI
+ Stack3 LiteLLM logical database dump
+ Stack4 Gitea application-native dump
+ external Git-backed portable user memory (MEMORY.md + USER.md)
```

Do not back up live PostgreSQL PGDATA as the normal DR mechanism. Use logical/application-aware recovery artifacts. Do not encode Docker-internal paths as architectural recovery contracts.

## 2. Normalized manifest contract

Each stack manifest contains a `recovery` object validated by [`recovery.schema.json`](recovery.schema.json):

```text
recovery
├── contract     REQUIRED in every stack
└── resources    OPTIONAL; present only when recovery resources exist
```

Valid modes are `reconstructable`, `managed`, and `mixed`. Resource classes are `persistent-data`, `persistent-identity`, and `externalized`. Version 1 strategies are `archive`, `postgres-custom-dump`, `gitea-native-dump`, `external-config`, and `git`.

## 3. Stack-by-stack decision

| Stack | Recovery mode | Durable recovery target | Decision |
|---|---|---|---|
| Stack0 Platform | `mixed` | platform PKI | **BACKUP** |
| Stack1 HAProxy/Web | `reconstructable` | none | **RECONSTRUCT** |
| Stack2 SearXNG/Firecrawl | `reconstructable` | none | **RECONSTRUCT** |
| Stack3 LiteLLM | `mixed` | LiteLLM DB + original `LITELLM_SALT_KEY` | **BACKUP + REQUIRE** |
| Stack4 Gitea | `managed` | complete logical/application state | **BACKUP** |
| Stack5 Dockhand | `reconstructable` | none | **RECONSTRUCT** |
| Stack6 Hermes | `reconstructable` | external Git `MEMORY.md` + `USER.md` only | **EXTERNAL** |

Stack0 PKI survives rebuild and is restored `pre-prepare`. Stack2 and Stack5 are disposable. LiteLLM uses a logical PostgreSQL dump rather than PGDATA and requires the original `LITELLM_SALT_KEY`. Gitea uses a controlled-offline native application dump.

Stack6 is fully replaceable. `SOUL.md` is runtime-generated Hermes/Nous Research behavior text and is not DR data. Hermes SQLite databases, caches, packages, sessions, logs and the complete sandbox tree are disposable. New Hermes-generated files remain disposable unless the platform explicitly promotes them to durable state.

## 4. Protected configuration

The operational `.env` is a protected recovery prerequisite outside Git. Recovery tooling must never print it, commit it, or place secret values into unprotected metadata. The final encrypted backup/rotation/off-host policy for `.env` remains open.

## 5. Planner and dry-run

```bash
python3 bkp-dr/dr.py plan all
python3 bkp-dr/dr.py backup all --dry-run
```

Planning classifies resources as `BACKUP`, `REQUIRE`, `EXTERNAL`, or `RECONSTRUCT`. Backup dry-run performs destination and runtime/source preflight. Destination precedence is `--destination`, then `DR_BACKUP_ROOT`, then `/opt/local-hybrid-ai-backups`.

The Stack6 manifest now declares `GITMEM_REPOSITORY` as the configured source for its external Git resource. [`dr_stack6_verify.py`](dr_stack6_verify.py) performs the stronger read-only portable-memory proof: configured origin/branch, tracked regular `MEMORY.md` + `USER.md`, clean working tree and local HEAD aligned with the existing remote-tracking branch. It performs no fetch/pull/commit/push/reset.

## 6. Execution filesystem contract

[`dr_filesystem.py`](dr_filesystem.py) prepares the selected backup root with mode `0700`, validates ownership and exercises same-parent atomic publication using a transient private probe. Existing non-conforming roots fail closed and are never silently chmod/chowned.

Validated reference destination:

```text
/opt/local-hybrid-ai-backups/   owner=root  mode=0700
```

## 7. Real backup/restore evidence

### Stack0

`dr_archive.py` creates the bounded PKI archive and `dr_archive_restore.py` verifies isolated extraction. Real backup and isolated restore verification have passed.

### Stack3

`dr_stack3_backup.py` creates a dependency-complete Stack0 + LiteLLM custom-format PostgreSQL dump. `dr_stack3_restore_verify.py` restores into a temporary database, validates table inventory/data presence and removes the temporary DB. Real backup and isolated restore verification have passed.

### Stack4

`dr_stack4_backup.py` creates a dependency-complete Stack0 + Gitea native dump. Consistency requires a brief controlled stop of Gitea. The helper derives the deployed Gitea execution context rather than assuming rootless paths/users. `dr_stack4_restore_verify.py` imports the SQLite dump into a temporary database and runs `git fsck` against restored repositories. Real controlled-offline backup and isolated restore verification have passed, including a fresh regression after removal of rootless-specific assumptions.

### Stack6

No backup artifact is created. The durable exception is external Git-backed user memory. Host qualification of [`dr_stack6_verify.py`](dr_stack6_verify.py) is required before marking this prerequisite fully verified.

## 8. Completed backup-set layout

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

[`backup-set.schema.json`](backup-set.schema.json) defines completed metadata. Secret values do not belong in metadata.

## 9. Intentionally excluded

The DR design excludes Firecrawl PostgreSQL/Redis/RabbitMQ state, SearXNG runtime/cache, physical PGDATA copies, Dockhand state, Gitea runner registration state, Docker containers/images/overlay internals, `.lock`, temporary files and migration markers.

For Stack6 it additionally excludes `SOUL.md`, all Hermes operational SQLite databases, caches, packages, sessions, logs, and all `service_-_hermes-sandbox` content.

## 10. Remaining work before full DR closure

```text
Stack0 backup + isolated restore                  DONE
Stack3 backup + isolated restore                  DONE
Stack4 consistent backup + isolated restore       DONE
Stack4 rootless/rootful-context hardening         DONE + real regression PASS
Stack6 persistence boundary                       DECIDED
Stack6 portable-memory verifier                   IMPLEMENTED; host qualification NEXT
protected .env backup policy                      OPEN
backup encryption/retention/off-host policy       OPEN
destination/source overlap hardening              OPEN
manifest validator type hardening                 OPEN
old archive publication-path hardening            OPEN
generic real backup all orchestration             OPEN
clean-environment full rebuild/restore proof       OPEN
```

No recovery design is complete until the artifacts/prerequisites can reproduce the intended platform in a clean environment without relying on undeclared runtime state.
