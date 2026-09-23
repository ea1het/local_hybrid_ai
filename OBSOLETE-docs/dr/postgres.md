<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Stack3 PostgreSQL disaster-recovery qualification

> **Strategy/qualification reference — the public backup command is `./local-ai backup`.**

[← DR index](README.md) · [Current DR workflow](howto.md) · [Documentation map](../TOC.md)

Stack3 declares its LiteLLM PostgreSQL state as a managed `postgres-custom-dump` recovery resource. The private Stack3 backup/verification helpers established this strategy before it was incorporated into the full manifest-driven backup pipeline.

## Backup strategy

For Stack3, dependency closure includes Stack0. A recovery point therefore includes the required platform material plus the Stack3 logical database artifact and the global protected configuration required by the full recovery contract.

The database artifact is produced through the running `litellm-postgres` service using PostgreSQL's custom logical-dump format with portable ownership semantics:

```text
pg_dump --format=custom --no-owner --no-acl
```

Database credentials are consumed only by the PostgreSQL client process and are not written to backup metadata or printed by the tool. `LITELLM_SALT_KEY` is declared separately as a sensitive external-config recovery resource and is protected through the recovery contract rather than embedded in database metadata.

The set is assembled privately, integrity metadata is validated before publication, and final publication uses the common atomic no-replace backup-set contract.

## Isolated restore verification

The PostgreSQL verifier validates backup metadata/checksums and the custom dump catalog, creates a unique throw-away PostgreSQL database, restores the dump into that isolated database, compares restored application-table inventory/data expectations and removes the temporary database afterwards.

It does not restore over the live LiteLLM database and does not restart application containers merely to verify an artifact.

## Current boundary

The historical Stack3 milestone originally stated that generic multi-stack backup and Gitea backup were not enabled. Those restrictions are retired: Stack4 has a native backup strategy and `./local-ai backup` now executes the full manifest-driven backup path through `src/local_ai_cli/backup/engine.py`.

The Stack3-specific helpers remain implementation/qualification tools, not supported operator interfaces. Current end-to-end recovery qualification is summarized in [DR status](status.md).

## Major-version upgrade

Backup/restore qualification above concerns disaster recovery — reconstructing a lost or corrupted deployment from a recovery point. A PostgreSQL **major-version upgrade** is a different, narrower operation reached through `./local-ai upgrade`, not `./local-ai backup`/`restore`: it changes the running server version in place using the existing deployment's own data, and it exists because PostgreSQL's on-disk data directory format is not compatible across major versions — the generic `env-version` upgrade recipe (swap an image tag, restart) cannot safely apply to it.

Stack3 `postgresql` declares a dedicated `postgres-major-upgrade` apply recipe (`src/local_ai_cli/upgrade/_postgres_major_upgrade.py`) instead. Applying a selection that uses it requires `--confirm-data-migration` in addition to `--yes`, and the selection must be the only one in that apply invocation. The sequence is:

1. Dump the running database with `pg_dump --format=custom`, and abort before any mutation if the dump is empty.
2. Stop the dependent application container, then the database container.
3. Move the existing data directory aside to `<name>.pre-upgrade-<timestamp>` — this directory is never deleted automatically, by design, at any point in the sequence, including on success.
4. Update the operational `.env` to the target image and start the database container against a fresh data directory.
5. Run the stack's normal deploy step, then restore the dump into the new server.
6. Verify the restored table inventory matches the pre-upgrade table inventory; a mismatch blocks the dependent application from restarting.
7. Restart the dependent application.

A working directory under `runtime_root/platform/postgres-major-upgrade/<component>-<timestamp>/` holds the dump for the duration of the operation and is removed only on full success; a failure at any step after the dump leaves both the dump and the moved-aside data directory in place for manual recovery, with the failure message naming their exact paths.

The old data directory left behind by a successful upgrade is an operator-owned artifact, not something the tool cleans up: recovering disk space, or deciding how long to keep it before deleting it, remains a manual operator decision (tracked in [pending work](../pending.md)).

This mechanism has been exercised only against mocked subprocess/Docker calls in the repository test suite (`tests/upgrade/test_postgres_major_upgrade.py`); it has not yet been run against a real deployment. Real-runtime qualification is required before it is trusted in production.
