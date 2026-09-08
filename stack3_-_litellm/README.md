# Stack3 — LiteLLM

LiteLLM is the AI model/MCP gateway. Stack3 now owns its PostgreSQL service and no longer depends on Stack2 for database infrastructure.

Internal endpoints:

```text
http://litellm:4000
postgresql://litellm-postgres:5432/<LITELLM_DB_NAME>
```

The public endpoint `https://gwia.casa.lan` is served by HAProxy when Stack1 is installed.

## Ownership

Stack3 owns:

```text
container: litellm
container: litellm-postgres
runtime:   ${BASE_PATH}/service_-_litellm
runtime:   ${BASE_PATH}/service_-_litellm-postgres
```

Its only hard stack dependency is Stack0.

## Environment

Stack3 consumes the shared root `.env` through its managed `./.env -> ../.env` compatibility link. Relevant variables are:

```text
STACKS_ROOT
BASE_PATH
NETWORK_NAME
LITELLM_IMAGE
LITELLM_VERSION
LITELLM_MASTER_KEY
LITELLM_SALT_KEY
UI_USERNAME
UI_PASSWORD
STORE_MODEL_IN_DB
LITELLM_DB_NAME
LITELLM_DB_USER
LITELLM_DB_PASSWORD
```

The PostgreSQL service host and port are internal Stack3 implementation details: `litellm-postgres:5432`.

`LITELLM_SALT_KEY` must be preserved once LiteLLM has encrypted state in PostgreSQL.

## Preparation lock

`.lock` means only that `01-prepare.sh` completed successfully. It does not mean PostgreSQL or LiteLLM are running or healthy.

## Fresh installation

```bash
cd /opt/docker/stacks/stack3_-_litellm
sudo ./01-prepare.sh
sudo ./02-postgres.sh
docker compose up -d litellm
docker compose ps
```

`02-postgres.sh` starts and validates the Stack3-owned PostgreSQL service. The official PostgreSQL image initializes the configured LiteLLM database and identity on a fresh data directory.

## Migration from the former Stack2 PostgreSQL

Existing deployments created before Stack3 became atomic keep LiteLLM state in `firecrawl-postgres`. Use the dedicated one-time helper:

```bash
sudo ./90-migrate-postgres-from-stack2.sh
```

The migration helper:

1. verifies that the currently running LiteLLM still points to `firecrawl-postgres`;
2. starts the empty Stack3 PostgreSQL target;
3. stops LiteLLM to freeze writes;
4. creates a custom-format `pg_dump` backup under `/root/litellm-postgres-migration-*`;
5. restores into `litellm-postgres`;
6. compares the user-table inventory;
7. recreates LiteLLM against the new database and waits for `healthy`;
8. leaves the old LiteLLM database in `firecrawl-postgres` untouched for rollback.

If the migration fails after LiteLLM is stopped, the helper attempts to recreate LiteLLM against the legacy Stack2 database automatically.

The old database must not be deleted until the new service has been validated operationally and the rollback window has been deliberately closed.
