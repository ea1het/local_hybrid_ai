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

The historical Stack3 milestone originally stated that generic multi-stack backup and Gitea backup were not enabled. Those restrictions are retired: Stack4 has a native backup strategy and `./local-ai backup` now executes the full manifest-driven backup path through the private `commands/recovery/backup-all.py` entry point.

The Stack3-specific helpers remain implementation/qualification tools, not supported operator interfaces. Current end-to-end recovery qualification is summarized in [DR status](status.md).
