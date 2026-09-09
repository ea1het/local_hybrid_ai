# Disaster recovery how-to

This document defines the disaster-recovery model for `local_hybrid_ai` before the backup/restore engine is implemented.

The design goal is deliberately small: preserve only state whose loss would materially prevent recovery. Everything else must be reconstructable from Git, protected configuration and fresh stack deployment.

> **Current implementation status:** the recovery contract and schema are defined here and in [`recovery.schema.json`](recovery.schema.json). The backup/restore engine is **not implemented yet**. Until that engine exists, this document is the architectural contract, not an executable runbook.

## 1. Recovery principles

The platform distinguishes physical persistence from disaster-recovery value.

A Docker volume, bind mount, database file or runtime directory is **not automatically a backup target**. A resource belongs in disaster recovery only when its loss would destroy durable data or durable identity that cannot be reconstructed safely.

The intended recovery set is:

```text
Git source at a known commit/tag
+ protected operational .env
+ Stack0 platform PKI
+ Stack3 LiteLLM logical database dump
+ Stack4 Gitea application-native dump
```

Everything else should be reconstructable or externalized.

Do not back up live PostgreSQL PGDATA as the normal DR mechanism. Use logical/application-aware recovery artifacts.

Do not encode Docker-internal paths such as `/var/lib/docker/overlay2/...` or named-volume mountpoints as architectural recovery contracts.

## 2. Normalized manifest contract

Each stack manifest will eventually contain a `recovery` object validated by [`recovery.schema.json`](recovery.schema.json).

The structure is intentionally normalized into two top-level blocks:

```text
recovery
├── contract     REQUIRED in every stack
└── resources    OPTIONAL; present only when recovery resources exist
```

### 2.1 Mandatory block: `contract`

Every stack must declare:

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

Valid `mode` values are:

| Mode | Meaning |
|---|---|
| `reconstructable` | The stack itself can be destroyed and rebuilt. It may only declare `externalized` resources. |
| `managed` | The stack owns durable recovery resources and cannot be considered recovered without them. |
| `mixed` | Some stack state is durable while the rest is intentionally reconstructable. |

### 2.2 Optional block: `resources`

`resources` is omitted when a stack has no managed or externalized recovery resources.

When present, every resource has the same normalized shape:

```json
{
  "id": "resource-id",
  "class": "persistent-data",
  "strategy": "postgres-custom-dump",
  "sensitive": true,
  "config": {}
}
```

The required common fields are:

| Field | Meaning |
|---|---|
| `id` | Stable machine-readable identifier inside the stack recovery contract. |
| `class` | Recovery semantics of the resource. |
| `strategy` | Engine adapter that creates/restores the artifact. |
| `sensitive` | Whether the resulting artifact/config must be treated as secret material. |

`config` is strategy-specific. Its exact allowed shape is enforced by `recovery.schema.json`; strategies do not invent arbitrary peer fields.

## 3. Resource classes

The schema intentionally exposes only three resource classes:

| Class | Meaning |
|---|---|
| `persistent-data` | Durable application data that must survive rebuild. |
| `persistent-identity` | Cryptographic or identity material whose replacement changes trust or decryptability. |
| `externalized` | Durable information lives outside the stack runtime and is recovered from another authoritative system. |

`ephemeral` and `reconstructable` are not resource classes. They are stack-level recovery semantics and are represented by `contract.mode`.

## 4. Recovery strategies

Version 1 defines only the strategies currently required by the platform:

| Strategy | Source | Intended use |
|---|---|---|
| `archive` | `runtime-path` | Preserve a bounded filesystem identity/resource such as platform PKI. |
| `postgres-custom-dump` | `postgres` | Logical PostgreSQL backup using custom-format dump semantics. |
| `gitea-native-dump` | `application` | Application-aware Gitea export containing database and durable repository/application state. |
| `external-config` | `environment` | Persistent identity already supplied by protected operational configuration. |
| `git` | `git` | Durable knowledge/state externalized to a Git repository. |

The manifest declares the logical resource and strategy. The future engine is responsible for the actual command implementation, verification, checksums, temporary paths, artifact naming, encryption and restore sequencing.

## 5. Restore phases

Managed filesystem/application resources may declare one of three normalized restore phases:

| Phase | Meaning |
|---|---|
| `pre-prepare` | Restore before stack PREPARE so preparation sees the existing identity/state. |
| `post-prepare-pre-deploy` | Prepare the fresh runtime/service substrate, restore durable state, then start the application. |
| `post-deploy` | Restore only after the application stack is already deployed. |

The schema deliberately does not allow arbitrary workflow strings such as `service:x:ready`. Recovery sequencing should remain a small platform lifecycle, not become an embedded workflow language.

## 6. Stack-by-stack recovery decision

The current DR classification is:

| Stack | Recovery mode | Durable recovery target | Decision |
|---|---|---|---|
| Stack0 Platform | `mixed` | platform PKI | **BACKUP** |
| Stack1 HAProxy/Web | `reconstructable` | none | **RECONSTRUCT** |
| Stack2 SearXNG/Firecrawl | `reconstructable` | none | **RECONSTRUCT** |
| Stack3 LiteLLM | `mixed` | LiteLLM DB + original `LITELLM_SALT_KEY` | **BACKUP** |
| Stack4 Gitea | `managed` | complete logical/application state | **BACKUP** |
| Stack5 Dockhand | `reconstructable` | none | **RECONSTRUCT** |
| Stack6 Hermes | `reconstructable` | knowledge/memory externalized to Git | **RECONSTRUCT** |

### 6.1 Stack0 — platform PKI

The platform trust identity must survive a rebuild. A representative future manifest block is:

```json
{
  "recovery": {
    "contract": {
      "schema_version": 1,
      "mode": "mixed"
    },
    "resources": [
      {
        "id": "platform-pki",
        "class": "persistent-identity",
        "strategy": "archive",
        "sensitive": true,
        "config": {
          "source": {
            "type": "runtime-path",
            "path": "${BASE_PATH}/service_-_platform/pki"
          },
          "restore": {
            "phase": "pre-prepare"
          }
        }
      }
    ]
  }
}
```

The engine must preserve the PKI as a bounded identity resource, including ownership/permissions needed by the platform. It must not generate a new PKI and then silently treat it as equivalent.

### 6.2 Stack1 — HAProxy/Web

No disaster-recovery artifact is required:

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

Rendered HAProxy/static-web runtime is installation output, not authoritative recovery state.

### 6.3 Stack2 — SearXNG/Firecrawl

No Stack2 runtime state is part of DR:

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

This intentionally includes Firecrawl PostgreSQL, Redis, RabbitMQ and SearXNG runtime/cache state. They may be persistent on disk for normal operation, but they are disposable for full disaster recovery.

### 6.4 Stack3 — LiteLLM

LiteLLM contains durable configured state. Preserve the application database logically and preserve the original salt through protected configuration.

```json
{
  "recovery": {
    "contract": {
      "schema_version": 1,
      "mode": "mixed"
    },
    "resources": [
      {
        "id": "litellm-database",
        "class": "persistent-data",
        "strategy": "postgres-custom-dump",
        "sensitive": true,
        "config": {
          "source": {
            "type": "postgres",
            "service": "litellm-postgres",
            "database_env": "LITELLM_DB_NAME",
            "user_env": "LITELLM_DB_USER"
          },
          "restore": {
            "phase": "post-prepare-pre-deploy"
          }
        }
      },
      {
        "id": "litellm-salt",
        "class": "persistent-identity",
        "strategy": "external-config",
        "sensitive": true,
        "config": {
          "source": {
            "type": "environment",
            "key": "LITELLM_SALT_KEY"
          }
        }
      }
    ]
  }
}
```

The target is the logical LiteLLM database, **not PGDATA**. A rebuild may create a new PostgreSQL cluster and new PostgreSQL administrative credential, restore the logical dump, and then start LiteLLM with the original `LITELLM_SALT_KEY`.

### 6.5 Stack4 — Gitea

Gitea is the durable source of truth for local repositories and application metadata. Preserve it with an application-aware dump rather than by naming selected internal directories in the manifest.

```json
{
  "recovery": {
    "contract": {
      "schema_version": 1,
      "mode": "managed"
    },
    "resources": [
      {
        "id": "gitea-state",
        "class": "persistent-data",
        "strategy": "gitea-native-dump",
        "sensitive": true,
        "config": {
          "source": {
            "type": "application",
            "service": "gitea"
          },
          "restore": {
            "phase": "post-prepare-pre-deploy"
          }
        }
      }
    ]
  }
}
```

The intended artifact must cover the logical Gitea state required to recover repositories and associated metadata, including the SQLite database and durable repository/application data supported by the native dump mechanism. The future engine must verify the exact command/flags against the deployed Gitea version before implementation.

Runner registration/runtime identity is not a core DR target; it may be re-registered after Gitea recovery.

### 6.6 Stack5 — Dockhand

Dockhand is an operational container visualizer/management UI. Its runtime volume is not valuable DR state.

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

Physical existence of `dockhand_data` does not change this classification.

### 6.7 Stack6 — Hermes

Hermes should be disposable compute/agent runtime. Durable memory, identity documents and knowledge should live in Git rather than in Hermes runtime databases/caches.

Target contract:

```json
{
  "recovery": {
    "contract": {
      "schema_version": 1,
      "mode": "reconstructable"
    },
    "resources": [
      {
        "id": "hermes-knowledge",
        "class": "externalized",
        "strategy": "git",
        "sensitive": false,
        "config": {
          "source": {
            "type": "git"
          }
        }
      }
    ]
  }
}
```

Architectural rule:

> If losing a Hermes runtime file would matter after a complete rebuild, that information is stored in the wrong place and should be externalized to Git/Gitea.

Caches, sessions, dynamically installed Python packages, model catalogs, SQLite operational databases, browser workspace, logs, sandbox state and similar runtime artifacts are not DR targets.

**Current migration note:** `SOUL.md` and any other operator-valued Hermes identity/knowledge that still exists only in mutable runtime must be externalized to Git before the future recovery engine can safely enforce Stack6 as fully reconstructable.

## 7. Global protected configuration

The operational `.env` is not a stack-owned backup resource. It is a platform recovery prerequisite and must have a protected backup outside Git.

It contains durable configuration/credentials including `LITELLM_SALT_KEY`. Recovery tooling must never print it, commit it, or bundle it into an unprotected general-purpose artifact.

The conceptual platform recovery inputs are therefore:

```text
source repository
protected .env
manifest-declared recovery artifacts
```

## 8. What is intentionally excluded

The DR design intentionally excludes:

- Firecrawl PostgreSQL data;
- Firecrawl Redis/RabbitMQ state;
- SearXNG cache/runtime state;
- PostgreSQL PGDATA physical copies as the normal database restore mechanism;
- Dockhand runtime volume;
- Hermes caches, sessions, packages, logs and operational SQLite state;
- Hermes sandbox workspace/state unless future requirements explicitly change;
- Gitea runner registration token/state;
- Docker containers and images;
- Docker overlay filesystem internals;
- `.lock`, temporary files and migration markers.

## 9. Future engine boundary

The next implementation phase should build a generic recovery engine that consumes stack manifests rather than hard-coding stack numbers.

Conceptually:

```text
manifest recovery contract
        +
current runtime observation
        +
strategy adapters
        ↓
backup / verify / restore
```

Expected adapters for version 1:

```text
archive
postgres-custom-dump
gitea-native-dump
external-config
git
```

The engine should validate declared resources against actual runtime/service topology before acting. A manifest path or service declaration is architectural intent; runtime observation confirms that the deployed system still matches it.

The engine must not implement destructive cleanup as part of backup or restore discovery.

## 10. Engine requirements to settle before coding

Before implementation, define at minimum:

- CLI shape (`backup`, `restore`, `verify`, `plan`);
- artifact directory/layout and naming;
- manifest validation integration;
- checksum/integrity metadata;
- encryption policy for sensitive artifacts;
- atomic temporary-file handling;
- retention policy, if any;
- backup consistency rules for Gitea and PostgreSQL;
- restore ordering across Stack0, Stack3 and Stack4;
- behavior when external prerequisites such as `.env` or Git knowledge are missing;
- dry-run/plan semantics;
- tests proving that reconstructable stacks never become accidental backup targets.

No recovery engine code should be considered complete until it can prove both sides of the contract: creation of a valid artifact and restoration into a clean deployment.
