# Layout v2 — Git checkout separated from persistent runtime

## Target layout

```text
/opt/docker/
├── stacks/                  # Git working tree: ea1het/local_hybrid_ai
│   ├── .git/
│   ├── stack1_-_haproxy_web/
│   ├── stack2_-_searxng_firecrawl/
│   ├── stack3_-_litellm/
│   ├── stack4_-_gitea/
│   ├── stack5_-_dockhand/
│   └── stack6_-_hermes/
│
└── runtime/                 # persistent runtime only
    ├── service_-_haproxy/
    ├── service_-_web/
    ├── service_-_searxng/
    ├── service_-_firecrawl-redis/
    ├── service_-_firecrawl-rabbitmq/
    ├── service_-_firecrawl-postgres/
    ├── service_-_litellm/
    ├── service_-_gitea/
    ├── service_-_gitea-runner/
    ├── service_-_hermes/
    ├── service_-_hermes-sandbox/
    └── service_-_hermes-memory/
```

`dockhand_data` remains an external Docker volume and is not moved into `runtime/`.

## Environment contract

Every operational stack `.env` uses:

```dotenv
STACKS_ROOT=/opt/docker/stacks
BASE_PATH=/opt/docker/runtime
```

`STACKS_ROOT` means source/checkout only.

`BASE_PATH` is retained for compatibility with the existing Compose files, but from Layout v2 onward it means **persistent runtime root only**. It must never point to the Git checkout.

## Migration preconditions

- all deployment containers are stopped
- operational `.env` files have been backed up outside the repository
- existing `service_-_*` directories are still under `/opt/docker`
- do not use `docker compose down -v`, `docker volume prune`, or `docker system prune`

## 1. Clone the complete repository

From the host:

```bash
cd /opt/docker

git clone \
  --branch feature/hermes-mcp-telegram-gitmem \
  --single-branch \
  https://github.com/ea1het/local_hybrid_ai.git \
  stacks
```

Verify:

```bash
git -C /opt/docker/stacks status --short
git -C /opt/docker/stacks branch --show-current
```

Expected branch:

```text
feature/hermes-mcp-telegram-gitmem
```

## 2. Restore the six operational `.env` files

Restore each previously backed-up `.env` into the corresponding directory below `/opt/docker/stacks`.

Example target paths:

```text
/opt/docker/stacks/stack1_-_haproxy_web/.env
/opt/docker/stacks/stack2_-_searxng_firecrawl/.env
/opt/docker/stacks/stack3_-_litellm/.env
/opt/docker/stacks/stack4_-_gitea/.env
/opt/docker/stacks/stack5_-_dockhand/.env
/opt/docker/stacks/stack6_-_hermes/.env
```

Never copy `.env.example` or `.env.template` over an operational `.env`.

## 3. Adapt only the layout keys in `.env`

Run from the repository root:

```bash
cd /opt/docker/stacks
sudo bash ./01-adapt-env-layout.sh
```

It requires all six `.env` files to exist before modifying any of them.

It changes only these keys:

```dotenv
STACKS_ROOT=/opt/docker/stacks
BASE_PATH=/opt/docker/runtime
```

Validate without printing secrets:

```bash
for f in /opt/docker/stacks/stack*/.env; do
  echo "=== $f ==="
  grep -E '^(STACKS_ROOT|BASE_PATH)=' "$f"
done
```

## 4. Move persistent service directories

Run:

```bash
cd /opt/docker/stacks
sudo bash ./00-migrate-runtime-layout.sh
```

The script:

- refuses to run if any container is running
- preflights every destination before moving anything
- moves only top-level `/opt/docker/service_-_*` directories
- never moves the old `stackX_-_*` directories
- never deletes persistent data
- writes `/opt/docker/runtime/.layout-v2` after a successful audit

Verify:

```bash
find /opt/docker/runtime -mindepth 1 -maxdepth 1 -type d -name 'service_-_*' -printf '%f\n' | sort
find /opt/docker -mindepth 1 -maxdepth 1 -type d -name 'service_-_*' -print
cat /opt/docker/runtime/.layout-v2
```

The second command should print nothing.

The old `/opt/docker/stackX_-_*` directories can remain temporarily as rollback copies. Do not run Compose from them after Layout v2 migration.

## 5. Prepare and start infrastructure in dependency order

### Stack1 — HAProxy + Web

```bash
cd /opt/docker/stacks/stack1_-_haproxy_web
rm -f .lock
sudo ./01-prepare.sh
docker compose up -d
```

### Stack2 — SearXNG + Firecrawl + PostgreSQL

```bash
cd /opt/docker/stacks/stack2_-_searxng_firecrawl
rm -f .lock
sudo ./01-prepare.sh
docker compose up -d
```

Wait until PostgreSQL is healthy:

```bash
docker compose ps
```

### Stack3 — LiteLLM

Before preparing, ensure its `.env` includes the Phase 1 pin:

```dotenv
LITELLM_IMAGE=ghcr.io/berriai/litellm-database
LITELLM_VERSION=1.99.1
```

Then:

```bash
cd /opt/docker/stacks/stack3_-_litellm
rm -f .lock
sudo ./01-prepare.sh
sudo ./02-postgres.sh
docker compose up -d --force-recreate litellm
```

Do not run `02-postgres.sh` while Stack2 PostgreSQL is stopped.

Validate existing inference before configuring MCP.

### Stack4 — Gitea

```bash
cd /opt/docker/stacks/stack4_-_gitea
rm -f .lock
sudo ./01-prepare.sh
sudo ./02-run.sh
```

### Stack5 — Dockhand

```bash
cd /opt/docker/stacks/stack5_-_dockhand
rm -f .lock
sudo ./01-prepare.sh
docker compose up -d
```

## 6. Stack6 remains last

Do not start Stack6 merely as part of the layout migration.

First complete the Phase 1 prerequisites:

1. LiteLLM MCP Gateway operational
2. Trivago MCP registered and tested
3. dedicated `hermes-mcp` virtual key created
4. private Gitea `hermes-memory` repository created with `MEMORY.md` and `USER.md`
5. Stack6 `.env` updated with Hermes version, MCP key, Telegram token and Git-memory repository
6. legacy Hermes memory reconciled with the Git repository

Then use the Stack6 Phase 1 sequence:

```bash
cd /opt/docker/stacks/stack6_-_hermes
rm -f .lock
sudo ./01-prepare.sh
sudo bash ./04-gitmem.sh
docker compose up -d --build --force-recreate
```

All Stack6 runtime paths resolve below:

```text
/opt/docker/runtime/service_-_hermes
/opt/docker/runtime/service_-_hermes-sandbox
/opt/docker/runtime/service_-_hermes-memory
```

## Rollback boundary

Until Layout v2 and Phase 1 are accepted:

- keep the old `/opt/docker/stackX_-_*` source directories
- keep the original Docker images
- keep the external `.env` backups
- do not delete `/opt/docker/runtime/service_-_*`

Moving a service directory from `/opt/docker/runtime/service_-_*` back to `/opt/docker/service_-_*` is a filesystem rollback and should only be done with all containers stopped.
