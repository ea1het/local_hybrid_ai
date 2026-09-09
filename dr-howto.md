# Disaster recovery how-to

This document defines the disaster-recovery model and recovery-engine contract for `local_hybrid_ai`.

The design goal is deliberately small: preserve only state whose loss would materially prevent recovery. Everything else must be reconstructable from Git, protected configuration and fresh stack deployment.

> **Current implementation status:** manifest recovery contracts are validated, `dr.py plan` is implemented, and `dr.py backup ... --dry-run` now plans the backup-set layout. No backup adapter, dump, archive, checksum generation, verification or restore execution is implemented yet.

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

Valid modes are:

| Mode | Meaning |
|---|---|
| `reconstructable` | The stack can be destroyed and rebuilt. It may only declare `externalized` resources. |
| `managed` | The stack owns durable recovery resources and cannot be considered recovered without them. |
| `mixed` | Some stack state is durable while the rest is intentionally reconstructable. |

When present, every resource uses the same normalized shape:

```json
{
  "id": "resource-id",
  "class": "persistent-data",
  "strategy": "postgres-custom-dump",
  "sensitive": true,
  "config": {}
}
```

Resource classes are `persistent-data`, `persistent-identity`, and `externalized`. `ephemeral` and `reconstructable` are stack-level semantics rather than resource classes.

## 3. Recovery strategies

Version 1 defines:

| Strategy | Source | Intended use |
|---|---|---|
| `archive` | `runtime-path` | Bounded filesystem identity/resource such as platform PKI. |
| `postgres-custom-dump` | `postgres` | Logical PostgreSQL custom-format dump. |
| `gitea-native-dump` | `application` | Application-aware Gitea export. |
| `external-config` | `environment` | Persistent identity supplied by protected operational configuration. |
| `git` | `git` | Durable knowledge/state externalized to Git. |

The manifest declares policy and logical source. The engine implements the command, consistency, artifact creation, integrity and restore semantics.

## 4. Restore phases

Managed filesystem/application resources may declare one of three phases:

| Phase | Meaning |
|---|---|
| `pre-prepare` | Restore before stack PREPARE so preparation sees the existing identity/state. |
| `post-prepare-pre-deploy` | Prepare the substrate, restore durable state, then start the application. |
| `post-deploy` | Restore only after the application stack is deployed. |

The contract deliberately avoids arbitrary workflow expressions. Recovery sequencing remains a small platform lifecycle.

## 5. Stack-by-stack decision

| Stack | Recovery mode | Durable recovery target | Decision |
|---|---|---|---|
| Stack0 Platform | `mixed` | platform PKI | **BACKUP** |
| Stack1 HAProxy/Web | `reconstructable` | none | **RECONSTRUCT** |
| Stack2 SearXNG/Firecrawl | `reconstructable` | none | **RECONSTRUCT** |
| Stack3 LiteLLM | `mixed` | LiteLLM DB + original `LITELLM_SALT_KEY` | **BACKUP + REQUIRE** |
| Stack4 Gitea | `managed` | complete logical/application state | **BACKUP** |
| Stack5 Dockhand | `reconstructable` | none | **RECONSTRUCT** |
| Stack6 Hermes | `reconstructable` | knowledge/memory externalized to Git | **EXTERNAL** |

### Stack0 — platform PKI

The trust identity survives rebuild. Manifest strategy: `archive`, restore phase `pre-prepare`. The engine must preserve the existing identity rather than generate a replacement and call it equivalent.

### Stack1 — HAProxy/Web

No recovery artifact. Rendered HAProxy/static-web runtime is installation output. TLS identity belongs to Stack0.

### Stack2 — SearXNG/Firecrawl

No recovery artifact. Firecrawl PostgreSQL, Redis, RabbitMQ and SearXNG runtime/cache state are intentionally disposable for full DR.

### Stack3 — LiteLLM

The LiteLLM application database is a `postgres-custom-dump` artifact restored `post-prepare-pre-deploy`. `LITELLM_SALT_KEY` is a required external configuration identity and is never copied into generic backup metadata.

The target is the logical LiteLLM database, not PGDATA. A rebuild may create a fresh PostgreSQL cluster/admin credential, restore the application dump, and start LiteLLM with the original salt.

### Stack4 — Gitea

Gitea is durable source-of-truth state. Strategy: `gitea-native-dump`. The artifact must cover repositories plus associated application metadata supported by the native dump mechanism. Runner registration/runtime identity is reconstructable.

The exact dump/restore flags must be verified against the deployed Gitea version before adapter execution is implemented.

### Stack5 — Dockhand

Reconstructable. The existence of `dockhand_data` does not make it a DR resource.

### Stack6 — Hermes

Hermes should be disposable agent/compute runtime. Durable memory, identity documents and knowledge should live in Git/Gitea.

> If losing a Hermes runtime file would matter after a complete rebuild, that information is stored in the wrong place and should be externalized to Git/Gitea.

Caches, sessions, dynamically installed packages, model catalogs, SQLite operational databases, browser workspace, logs and sandbox state are not DR targets.

`SOUL.md` and any other operator-valued identity/knowledge that still exists only in mutable runtime remains a migration gap and must be externalized before Stack6 can be treated as fully disposable in practice.

## 6. Global protected configuration

The operational `.env` is not a stack-owned backup artifact. It is a protected recovery prerequisite outside Git. It contains durable configuration/credentials including `LITELLM_SALT_KEY`.

Recovery tooling must never print `.env`, commit it, or place secret values into unprotected metadata.

## 7. Read-only planner

The first engine milestone is:

```bash
python3 dr.py plan all
python3 dr.py plan 3
python3 dr.py plan 6 --target
python3 dr.py plan all --json
```

It resolves the same dependency graph as installation and classifies entries as:

```text
BACKUP       create a managed artifact
REQUIRE      required protected prerequisite, not a generic artifact
EXTERNAL     authoritative state lives elsewhere
RECONSTRUCT  no recovery artifact
```

Planning does not inspect Docker runtime or secret values and makes no changes.

## 8. Backup-set dry-run

The second engine milestone plans a backup set without creating it:

```bash
python3 dr.py backup all --dry-run
python3 dr.py backup 3 --dry-run
python3 dr.py backup all --dry-run --json
```

Calling `dr.py backup` without `--dry-run` currently fails closed because adapter execution is not implemented.

For the current platform, `backup all --dry-run` must plan exactly three artifacts:

```text
artifacts/stack0/platform-pki.tar
artifacts/stack3/litellm-database.dump
artifacts/stack4/gitea-state.zip
```

and two non-artifact prerequisites:

```text
stack3 litellm-salt       REQUIRE / external-config
stack6 hermes-knowledge   EXTERNAL / git
```

Reconstructable stacks never acquire artifact slots merely because they own persistent files or Docker volumes.

## 9. Backup-set layout

A completed backup set will use this logical layout:

```text
<backup-set>/
├── backup.json
├── checksums.sha256
└── artifacts/
    ├── stack0/
    │   └── platform-pki.tar
    ├── stack3/
    │   └── litellm-database.dump
    └── stack4/
        └── gitea-state.zip
```

`backup.json` is normative metadata. `checksums.sha256` is a human/tool-friendly integrity index over artifact files. The backup set is not considered complete merely because files with these names exist.

[`backup-set.schema.json`](backup-set.schema.json) defines the metadata contract for a **completed** backup set. Dry-run JSON deliberately uses `kind: local-hybrid-ai-backup-plan`, not `local-hybrid-ai-backup-set`, and contains no fake checksum or size values.

A completed `backup.json` must contain, at minimum:

- schema version and kind;
- creation timestamp;
- exact Git source commit;
- requested selectors and resolved stacks;
- each real artifact's stack/resource identity, strategy, sensitivity, restore phase and relative path;
- SHA-256 and byte size for each real artifact;
- non-artifact prerequisites (`REQUIRE` / `EXTERNAL`).

Secret values, `.env` contents, database passwords and source-specific manifest config do not belong in backup metadata.

## 10. Integrity and completion rules

The future executing backup command must build into a temporary backup-set directory and publish/rename it only after all requested artifacts succeed and integrity metadata is complete.

A completed set should therefore satisfy:

```text
all BACKUP resources produced
+ every artifact is non-missing
+ SHA-256 recorded
+ size recorded
+ checksums.sha256 matches backup.json
+ required prerequisites validated without exposing values
+ backup.json validates against backup-set.schema.json
```

A partially generated directory must never be presented as a successful backup set.

## 11. What is intentionally excluded

The DR design excludes:

- Firecrawl PostgreSQL data;
- Firecrawl Redis/RabbitMQ state;
- SearXNG cache/runtime state;
- PostgreSQL PGDATA physical copies as the normal database restore mechanism;
- Dockhand runtime volume;
- Hermes caches, sessions, packages, logs and operational SQLite state;
- Hermes sandbox workspace/state unless requirements change;
- Gitea runner registration token/state;
- Docker containers/images and overlay filesystem internals;
- `.lock`, temporary files and migration markers.

## 12. Remaining engine milestones

The generic engine should continue without stack-number conditionals. The remaining sequence is:

```text
runtime/source preflight
-> adapter execution
   archive
   postgres-custom-dump
   gitea-native-dump
-> checksum + size collection
-> completed backup.json
-> backup-set verify
-> restore planning/execution by declared restore phase
```

Before real adapter execution, settle and test:

- backup destination and permissions;
- encryption policy for sensitive artifacts;
- temporary directory and atomic publication semantics;
- PostgreSQL consistency and command details;
- exact Gitea native dump/restore command for the pinned version;
- prerequisite verification without displaying secret values;
- failure cleanup that never destroys source/runtime state.

No recovery engine is complete until it proves both artifact creation and restoration into a clean deployment.
