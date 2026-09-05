# Installation

This document describes the permanent installation layout for `local_hybrid_ai`.

The repository is deployed as one Git working tree and persistent application state is kept outside that checkout.

## Filesystem layout

```text
/opt/docker/
├── stacks/                  # Git checkout: ea1het/local_hybrid_ai
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

`dockhand_data` remains an external Docker volume.

## Environment contract

Every operational stack uses:

```dotenv
STACKS_ROOT=/opt/docker/stacks
BASE_PATH=/opt/docker/runtime
```

`STACKS_ROOT` is source code only. `BASE_PATH` is persistent runtime only.

Operational `.env` files contain deployment-specific values and secrets and must not be committed.

## Clean installation

Clone the repository once:

```bash
sudo mkdir -p /opt/docker
cd /opt/docker
sudo git clone https://github.com/ea1het/local_hybrid_ai.git stacks
cd /opt/docker/stacks
```

For each stack, create its operational `.env` from the supplied example/template and edit the deployment-specific values. Never commit those operational `.env` files.

The normal deployment order is:

1. Stack1 — HAProxy and static web
2. Stack2 — SearXNG and Firecrawl
3. Stack3 — LiteLLM
4. Stack4 — Gitea
5. Stack5 — Dockhand
6. Stack6 — Hermes and its sandbox

### Stack1

```bash
cd /opt/docker/stacks/stack1_-_haproxy_web
cp .env.example .env
# edit .env
sudo ./01-prepare.sh
docker compose up -d
```

### Stack2

```bash
cd /opt/docker/stacks/stack2_-_searxng_firecrawl
cp .env.example .env
# edit .env
sudo ./01-prepare.sh
docker compose up -d
```

Wait until the Firecrawl dependencies are healthy before continuing.

### Stack3

LiteLLM is pinned by image and version in the operational `.env`.

```bash
cd /opt/docker/stacks/stack3_-_litellm
cp .env.example .env
# edit .env
sudo ./01-prepare.sh
sudo ./02-postgres.sh
docker compose up -d --force-recreate litellm
```

Validate the local inference route before adding optional MCP integrations.

### Stack4

```bash
cd /opt/docker/stacks/stack4_-_gitea
cp .env.example .env
# edit .env
sudo ./01-prepare.sh
sudo ./02-run.sh
```

### Stack5

```bash
cd /opt/docker/stacks/stack5_-_dockhand
cp .env.example .env
# edit .env
sudo ./01-prepare.sh
docker compose up -d
```

### Stack6

Stack6 is deliberately last because it depends on the model gateway and, when enabled, external integration configuration.

Create the operational environment from `.env.template`, then configure at least:

```dotenv
STACKS_ROOT=/opt/docker/stacks
BASE_PATH=/opt/docker/runtime
HERMES_IMAGE=nousresearch/hermes-agent
HERMES_VERSION=v2026.8.31
HERMES_MEMORY_SERVICE=service_-_hermes-memory
LITELLM_MCP_URL=http://litellm:4000/mcp
GITMEM_BRANCH=main
```

Secrets such as LiteLLM keys, Telegram tokens and Git credentials remain outside Git.

The configured private Git memory repository must already contain regular files named:

```text
MEMORY.md
USER.md
```

Then:

```bash
cd /opt/docker/stacks/stack6_-_hermes
sudo ./01-prepare.sh
sudo ./04-gitmem.sh
docker compose up -d --build
```

`04-gitmem.sh` prepares and validates the Git-backed memory working tree. It does not pull, merge, rebase, commit or push.

## Deployment state

Preparation scripts create a local `.lock` only after their audits succeed. Operational `.env` and `.lock` files are deployment state, not source configuration.

Persistent application data must stay below `/opt/docker/runtime`; do not copy databases, generated runtime configuration, session state or secrets into `/opt/docker/stacks`.

## Updating the checkout

Treat `/opt/docker/stacks` as an ordinary Git working tree. Do not edit tracked deployment files directly on the server unless the change is intentionally going back to Git.

Before updating:

```bash
cd /opt/docker/stacks
git status --short
git branch --show-current
```

A healthy deployment checkout should have no tracked local modifications. Operational `.env` and runtime data must remain outside Git tracking.

After pulling a change, use the affected stack's documented prepare/recreate procedure rather than assuming that `docker restart` applies new configuration.

## Security boundary

Never commit real values for:

- operational `.env` files
- LiteLLM master or virtual keys
- local-model API tokens
- Telegram bot tokens
- Buzz private keys or auth tags
- TLS private keys generated for a real deployment
- SSH private keys
- database passwords
- Hermes runtime databases, sessions or auth state

The repository contains source configuration and safe examples only. Persistent runtime state belongs under `/opt/docker/runtime`.
