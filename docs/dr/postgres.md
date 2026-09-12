# Stack3 PostgreSQL disaster recovery

This milestone enables a real, dependency-complete backup for requested Stack3 without enabling generic multi-stack execution.

## Backup

Run:

```bash
python3 dr_stack3_backup.py 3 --destination /opt/local-hybrid-ai-backups
```

The command resolves Stack3 as `[0, 3]` and creates one atomic backup set containing:

```text
artifacts/stack0/platform-pki.tar
artifacts/stack3/litellm-database.dump
```

The Stack3 database artifact is produced with PostgreSQL administrator role `postgres` using the Stack3-managed secret mounted read-only inside `litellm-postgres` at `/run/secrets/postgres_admin_password`.

The password is read only inside the container and exported only to the child PostgreSQL client process as `PGPASSWORD`. It is never written to backup metadata or printed by the tool.

The logical dump command uses custom format and portable ownership semantics:

```text
pg_dump --format=custom --no-owner --no-acl
```

`LITELLM_SALT_KEY` remains an external protected prerequisite and is not copied into the backup set.

The set is assembled in a private temporary sibling directory, all hashes and metadata are validated before publication, and publication uses the existing atomic no-replace filesystem contract.

## Restore verification

Run:

```bash
python3 dr_stack3_restore_verify.py /opt/local-hybrid-ai-backups/backup-YYYYMMDDTHHMMSSZ
```

The verifier checks `backup.json`, `checksums.sha256`, artifact sizes and SHA-256 values, validates the custom dump catalog, creates a unique throw-away PostgreSQL database, restores the persistent dump into that database with the LiteLLM application role, compares the restored user-table inventory with the live source database, checks restored data presence, and removes the throw-away database.

It never restores over `LITELLM_DB_NAME`, does not modify the live LiteLLM database, and does not restart containers.

## Current boundary

This milestone does **not** enable `dr.py backup all`. Gitea still has no real backup adapter. Generic multi-stack execution remains blocked until every required managed strategy has a tested adapter.
