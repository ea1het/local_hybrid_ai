# Stack3 — LiteLLM

LiteLLM acts as the AI gateway and uses the PostgreSQL instance already deployed by Stack2. The PostgreSQL infrastructure is shared, but LiteLLM has its own user, password and database.

LiteLLM does not terminate TLS. Its internal endpoint is:

```text
http://litellm:4000
```

The public endpoint `https://gwia.casa.lan` is served by HAProxy.

## Structure

```text
stack3_-_litellm/
├── .env
├── docker-compose.yml
├── 01-prepare.sh
├── 02-postgres.sh
├── README.md
└── config/
    └── litellm/
        └── config.yaml
```

Operational path:

```text
${BASE_PATH}/service_-_litellm/config/config.yaml
```

## `.env`

Current variables:

```text
BASE_PATH
LITELLM_MASTER_KEY
LITELLM_SALT_KEY
UI_USERNAME
UI_PASSWORD
STORE_MODEL_IN_DB
POSTGRES_HOST
POSTGRES_PORT
LITELLM_DB_NAME
LITELLM_DB_USER
LITELLM_DB_PASSWORD
```

`STACK2_ENV_STATE` and `LITELLM_PORT` were removed because they belonged to the old installation flow and are not needed in the current Compose setup.

All secrets must exist before running `01-prepare.sh`. In particular, `LITELLM_SALT_KEY` must be preserved consistently once LiteLLM has encrypted data in PostgreSQL.

## New installation process

### 1. Stack2 must be operational

`firecrawl-postgres` must exist and be running.

### 2. Prepare LiteLLM

```bash
cd /opt/docker/stack3_-_litellm
sudo ./01-prepare.sh
```

This step validates `.env`, migrates the old `/opt/docker/litellm` if needed, creates `redlocal` if missing, and replaces LiteLLM's operational configuration.

It does not create `.lock`, because PostgreSQL provisioning is still pending.

### 3. Provision PostgreSQL

```bash
sudo ./02-postgres.sh
```

`02-postgres.sh` reads directly, only during provisioning:

```text
${BASE_PATH}/stack2_-_searxng_firecrawl/.env
```

From there it only reads:

```text
POSTGRES_USER
POSTGRES_PASSWORD
POSTGRES_DB
```

Those credentials are not copied or written into the Stack3 `.env` file. The script creates or updates the LiteLLM role, creates its database if it is missing, ensures ownership, and checks a connection using the final LiteLLM credentials.

If it completes successfully, it creates `.lock`.

### 4. Start LiteLLM

```bash
docker compose up -d
docker compose ps
docker compose logs -f litellm
```

## Deliberate rebuild

```bash
rm .lock
sudo ./01-prepare.sh
sudo ./02-postgres.sh
```

`02-postgres.sh` is safe with respect to persistence: it creates or updates the LiteLLM PostgreSQL identity, but does not delete the database or its tables.
