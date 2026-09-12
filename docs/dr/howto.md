# Disaster recovery how-to

This document defines the disaster-recovery model and recovery-engine contract for `local_hybrid_ai`.

The design goal is deliberately small: preserve only state whose loss would materially prevent recovery. Everything else must be reconstructable from Git, protected configuration and fresh stack deployment.

## 1. Recovery principles

A Docker volume, bind mount, database file or runtime directory is not automatically a backup target. Recovery policy is declared in stack manifests and verified with bounded strategy-specific tooling.

The intended recovery inputs are:

```text
Git source at a known commit/tag
+ protected operational .env carried by the complete backup set (ADR-0001)
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

Stack6 is fully replaceable. `SOUL.md` is runtime-generated Hermes/Nous Research behavior text and is not DR data. Hermes SQLite databases, caches, packages, sessions, logs and the complete sandbox tree are disposable. New Hermes-generated files remain disposable unless the platform explicitly promotes them to durable state. The Stack6 Git remote is configuration, not a Stack4 dependency: it may be Gitea, another Git service/SaaS, or another configured repository.

## 4. Protected configuration

ADR-0001 accepts the current pragmatic model: every complete `backup all` set carries an exact protected copy of the operational root `.env` as `artifacts/global/operational.env`, mode `0600`, inside a private `0700` backup set. Recovery tooling must never print it or commit it. Encryption/retention/off-host protection remains later hardening; it does not change the logical requirement to restore the operational configuration before PREPARE.

## 5. Planner, dry-run and real backup all

```bash
python3 bkp-dr/dr.py plan all
python3 bkp-dr/dr.py backup all --dry-run
python3 bkp-dr/backup-all.py --json
```

Planning classifies resources as `BACKUP`, `REQUIRE`, `EXTERNAL`, or `RECONSTRUCT`. Deployment discovery for real `backup all` uses each manifest/lifecycle `required_containers`, after validating container ownership. Stack0 is always included. For other stacks, the presence of any required container marks the stack deployed; a partial/broken deployment is therefore not silently omitted and must pass normal runtime/source preflight.

Real backup execution stages all artifacts privately, performs fallible integrity work before publication, writes metadata/checksums, and publishes the final `backup-*` directory atomically with no replacement of an existing recovery point.

The Stack6 manifest declares `GITMEM_REPOSITORY` as the configured source for its external Git resource. [`dr_stack6_verify.py`](dr_stack6_verify.py) performs the stronger read-only portable-memory proof: configured origin/branch, tracked regular `MEMORY.md` + `USER.md`, clean working tree and local HEAD aligned with the existing remote-tracking branch. It performs no fetch/pull/commit/push/reset.

## 6. Execution filesystem contract

[`dr_filesystem.py`](dr_filesystem.py) prepares the selected backup root with mode `0700`, validates ownership and exercises same-parent atomic publication using a transient private probe. Existing non-conforming roots fail closed and are never silently chmod/chowned.

Validated reference destination:

```text
/opt/local-hybrid-ai-backups/   owner=root  mode=0700
```

## 7. Real backup/restore evidence

### Stack0

`dr_archive.py` creates the bounded PKI archive and `dr_archive_restore.py` verifies isolated extraction. Real backup and isolated restore verification have passed. The verifier now accepts a complete multi-resource backup set and selects the Stack0 `platform-pki` archive rather than assuming a Stack0-only set.

### Stack3

`dr_stack3_backup.py` creates the LiteLLM custom-format PostgreSQL dump. `dr_postgres_artifact_verify.py` verifies the dump stored in a complete recovery point by restoring it into a temporary database, comparing the restored table inventory, checking non-empty data presence and removing the temporary database. Live LiteLLM is not modified.

### Stack4

`dr_stack4_backup.py` creates the Gitea native dump. Consistency requires a brief controlled stop of Gitea. The helper derives the deployed Gitea execution context rather than assuming rootless paths/users. `dr_stack4_restore_verify.py` can select Stack4 from a complete backup set, imports the SQLite dump into a temporary database and runs `git fsck` against restored repositories. Live Gitea is not modified by restore verification.

### Stack6

No backup artifact is created. The durable exception is external Git-backed user memory. Host qualification of [`dr_stack6_verify.py`](dr_stack6_verify.py) passed: the configured repository was clean/aligned and contained tracked regular `MEMORY.md` + `USER.md`. `SOUL.md`, Hermes runtime and sandbox state are not required.

## 8. Completed backup-set layout

A complete set uses:

```text
/opt/local-hybrid-ai-backups/
└── backup-YYYYMMDDTHHMMSSZ/
    ├── backup.json
    ├── checksums.sha256
    └── artifacts/
        ├── global/
        │   └── operational.env
        └── stackN/
            └── resource artifact
```

[`backup-set.schema.json`](backup-set.schema.json) defines completed metadata. Secret values do not belong in metadata.

The first fully qualified global recovery point is:

```text
/opt/local-hybrid-ai-backups/backup-20260911T004927Z
source commit: f732f0e1bca533556d9a60fef5bd373b51675da2
resolved stacks: 0,1,2,3,4,5,6
```

Its creation passed atomically with four artifacts (`operational.env`, Stack0 PKI, Stack3 LiteLLM DB, Stack4 Gitea) and two declared prerequisites. The exact stored set then passed artifact-level recovery qualification: all checksums OK; PKI isolated extraction/fingerprint PASS; LiteLLM stored dump restored 75/75 tables with 25 non-empty tables and temporary DB cleanup PASS; Gitea stored dump restored 116 SQLite tables with 38 non-empty tables and 8/8 repositories passing `git fsck`; `.env` live/backup SHA-256 matched; Stack6 external Git verification PASS. Restore verifiers did not modify the live services.

## 9. Intentionally excluded

The DR design excludes Firecrawl PostgreSQL/Redis/RabbitMQ state, SearXNG runtime/cache, physical PGDATA copies, Dockhand state, Gitea runner registration state, Docker containers/images/overlay internals, `.lock`, temporary files and migration markers.

For Stack6 it additionally excludes `SOUL.md`, all Hermes operational SQLite databases, caches, packages, sessions, logs, and all `service_-_hermes-sandbox` content.

## 10. Remaining work before full DR closure

```text
Stack0 backup + isolated restore                  DONE
Stack3 backup + stored-artifact isolated restore  DONE
Stack4 consistent backup + isolated restore       DONE
Stack4 rootless/rootful-context hardening         DONE + real regression PASS
Stack6 persistence boundary + verifier             DONE + host PASS
protected .env backup policy                      DONE via ADR-0001
real atomic backup all                             DONE + host PASS
full recovery-point artifact qualification         DONE + host PASS
generic restore all orchestration                  NEXT
clean-environment full rebuild/restore proof       OPEN
backup encryption/retention/off-host policy        HARDENING
```

No recovery design is complete until the artifacts/prerequisites can reproduce the intended platform in a clean environment without relying on undeclared runtime state. Do not destroy the reference host to test recovery; use an isolated clean environment until the operator explicitly authorizes destructive testing.
