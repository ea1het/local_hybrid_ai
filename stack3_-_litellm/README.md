# Stack3 — LiteLLM + PostgreSQL

Stack3 is the AI model-policy and MCP gateway. It is atomic, requires only Stack0 and provides `ai.gateway` and `ai.mcp-gateway`.

```mermaid
flowchart LR
    A[Applications / Hermes] --> LL[LiteLLM :4000]
    LL --> LOCAL[Local inference]
    LL -.->|explicit routing policy| CLOUD[Optional cloud APIs]
    A -->|MCP via gateway| LL
    LL --> MCP[Upstream MCP servers]
    LL --> PG[(litellm-postgres)]
```

Stack6 requires these two AI capabilities. Stack3 does not depend on Stack2.

## Ownership

```text
containers:
  litellm
  litellm-postgres

runtime:
  ${BASE_PATH}/service_-_litellm
  ${BASE_PATH}/service_-_litellm-postgres
```

Internal endpoints:

```text
http://litellm:4000
litellm-postgres:5432
```

Stack1 may expose LiteLLM through HAProxy, but Stack1 is optional from Stack3's dependency perspective.

## PostgreSQL identity model

Stack3 owns a dedicated PostgreSQL cluster. As with Stack2, administrative and application database identities are separated.

```text
litellm-postgres
├── postgres
│   administrative/bootstrap role
│   password outside .env:
│   ${BASE_PATH}/service_-_litellm-postgres/secret/postgres_admin_password
│
└── ${LITELLM_DB_USER}
    LiteLLM application role
    database: ${LITELLM_DB_NAME}
    password: LITELLM_DB_PASSWORD in protected operational .env
```

The `postgres` role is reserved for cluster administration/bootstrap. LiteLLM uses the dedicated application role in normal operation.

`LITELLM_SALT_KEY` and the LiteLLM logical database are the critical DR identities/state. Database credentials must be preserved or rotated deliberately during normal operation, but the PostgreSQL administrative password itself may be regenerated for a completely fresh DR cluster.

## PGDATA safety contract

The dedicated cluster lives at:

```text
${BASE_PATH}/service_-_litellm-postgres/data
```

PREPARE never changes owner/mode/inode of an existing PGDATA.

```mermaid
flowchart TD
    P[01-prepare.sh] --> E{PGDATA exists?}
    E -->|yes| V[Validate real directory]
    V --> K[Preserve inode / owner / mode]
    E -->|no| N[Create empty directory]
    N --> I[PostgreSQL lifecycle initializes it]
```

Do not use recursive `chown`, database resets or fresh-cluster recreation as routine configuration repair.

For disaster recovery, however, PGDATA is **not** the backup artifact. Stack3 recovery uses a logical custom-format PostgreSQL dump of the LiteLLM application database. See [`../dr-howto.md`](../dr-howto.md).

## Preparation and start

```bash
cd /opt/docker/stacks/stack3_-_litellm
sudo ./01-prepare.sh
sudo ./02-postgres.sh
docker compose up -d litellm
docker compose ps
```

`01-prepare.sh` requires Stack0, validates the shared network and environment, prepares/preserves Stack3-owned runtime, generates or preserves the PostgreSQL administrative runtime secret, synchronizes managed LiteLLM configuration, validates Compose and writes `.lock` only after success.

`02-postgres.sh` establishes/validates the dedicated PostgreSQL service and application database contract before LiteLLM is started.

`.lock` means PREPARED only. It is not a PostgreSQL or LiteLLM health signal.

Useful bounded database validation after maintenance:

```bash
docker exec litellm-postgres psql -U postgres -d postgres -Atc 'SELECT 1;'
docker exec litellm-postgres psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c 'CHECKPOINT;'
```

## Disaster recovery

Target manifest semantics:

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

The protected operational `.env` supplies the original `LITELLM_SALT_KEY`. A fresh PostgreSQL cluster may be created, the logical dump restored, and LiteLLM then started with the matching salt.

## Re-preparation

Removing `.lock` is an explicit maintenance operation. If PREPARE is deliberately repeated against an existing deployment, PGDATA owner/mode/inode, database secrets, `LITELLM_SALT_KEY` and bind-directory identity must remain unchanged.

Historical migration helpers are not part of the current repository or installation path. The repository describes and deploys only the converged architecture.

## Security

Do not commit or rotate casually: `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY`, inference/MCP virtual keys, application database credentials or the PostgreSQL administrative runtime secret. Provider escalation belongs behind LiteLLM policy rather than being silently configured in consuming agents.
