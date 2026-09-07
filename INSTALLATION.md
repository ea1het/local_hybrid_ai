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
│   ├── stack6_-_hermes/
│   └── stack7_-_xyops/
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
    ├── service_-_hermes-memory/
    ├── service_-_xyops/
    └── service_-_xysat/
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
6. Stack6 — Hermes, isolated sandbox and Git-backed memory
7. Stack7 — xyOps conductor and dedicated xySat scheduler worker

### Stack1

TLS material is deployment-specific and is not stored in Git. Generate it locally before running `01-prepare.sh`:

```bash
cd /opt/docker/stacks/stack1_-_haproxy_web
cp .env.example .env
# edit .env

cd config/haproxy
bash generate.txt
cd ../..

sudo ./01-prepare.sh
docker compose up -d
```

The generated `casa.lan.crt` and `casa.lan.key` files are intentionally ignored by Git.

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

LiteLLM is also the shared MCP policy boundary. Upstream MCP servers and MCP-scoped virtual keys are managed dynamically in LiteLLM rather than committed to Stack3 source configuration.

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

Stack6 depends on the model gateway and, when enabled, external integration configuration. Stack7 is deployed afterwards because it schedules controlled maintenance against Stack6 runtime state.

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
docker compose ps
```

`04-gitmem.sh` prepares and validates the Git-backed memory working tree. It does not pull, merge, rebase, commit or push. Periodic synchronization belongs to Stack7.

For the currently validated Hermes version, apply the temporary terminal-timeout workaround after the containers are healthy:

```bash
sudo ./03-temporary-fix-issue-74116-terminal-timeout.sh
```

Keep this workaround only while the corresponding upstream Hermes issue remains unresolved for the deployed version.

If Telegram is enabled, pair or allowlist the intended user after Stack6 is healthy. If MCP is enabled, validate discovery first and then perform a real end-to-end MCP tool call through LiteLLM.

### Stack7

Stack7 adds scheduling without giving the scheduler the Docker socket, privileged mode, host networking or unrestricted host filesystem access.

Create the operational environment:

```bash
cd /opt/docker/stacks/stack7_-_xyops
cp .env.example .env
chmod 600 .env
# review .env
sudo ./01-prepare.sh
```

The validated image pins are currently:

```dotenv
XYOPS_IMAGE=ghcr.io/pixlcore/xyops
XYOPS_VERSION=v1.0.96
XYSAT_IMAGE=ghcr.io/pixlcore/xysat
XYSAT_VERSION=v1.0.45
```

Start the conductor first:

```bash
docker compose up -d xyops
docker compose ps xyops

docker exec xyops \
  curl -fsS http://127.0.0.1:5522/api/app/ping
```

Expected response:

```json
{"code":0}
```

Browser access is through HAProxy at:

```text
https://xyops.casa.lan
```

The conductor itself remains internal at `xyops:5522` on `redlocal`.

#### Enroll xySat

Enroll the dedicated xySat worker only after the conductor is operational.

Use the temporary bootstrap flow generated by the xyOps UI. The bootstrap token is sensitive and temporary: do not commit it, store it in `.env`, or paste it into documentation.

The resulting permanent worker identity must be stored at:

```text
/opt/docker/runtime/service_-_xysat/config/config.json
```

with mode:

```text
0600
```

The active worker path must resolve to:

```text
host   = xyops
port   = 5522
secure = false
```

Once enrolled, start the worker profile:

```bash
docker compose --profile worker up -d xysat
docker compose --profile worker ps

docker exec xysat getent hosts xyops
docker exec xysat curl -fsS http://xyops:5522/api/app/ping
```

The worker should appear Online in the xyOps Servers UI.

#### Scheduler-specific Gitea identity

Before enabling the memory-sync job, provision a dedicated scheduler SSH identity under:

```text
/opt/docker/runtime/service_-_xysat/ssh/
```

The worker must use scheduler-specific `id_ed25519`, `known_hosts` and `ssh_config` material rather than mounting `/root/.ssh`. Authorize only the access required for the Hermes memory repository and keep strict host-key checking enabled.

#### Create the validated jobs

Create the following xyOps events against the dedicated scheduler worker:

```text
Hermes Memory Sync
  Manual trigger
  Every 10 minutes
  Maximum concurrent jobs: 1
  Maximum runtime: 300 seconds

Hermes Sandbox Audit
  Manual trigger
  Daily at 03:30 Europe/Madrid
  Maximum concurrent jobs: 1
  Maximum runtime: 300 seconds
```

The corresponding scripts are:

```text
/opt/xyops/jobs/hermes-memory-sync.sh
/opt/xyops/jobs/hermes-sandbox-audit.sh
```

Validate both jobs manually before relying on their automatic triggers.

The memory job may write only to the Git-backed Hermes memory worktree. The sandbox audit sees only the sandbox workspace and sees it read-only. The audit performs no automatic deletion.

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

A healthy deployment checkout should have no tracked local modifications. Operational `.env`, `.lock`, generated TLS material and runtime data must remain outside Git tracking.

After pulling a change, use the affected stack's documented prepare/recreate procedure rather than assuming that `docker restart` applies new configuration.

## Security boundary

Never commit real values for:

- operational `.env` files
- LiteLLM master, inference or MCP virtual keys
- local-model API tokens
- Telegram bot tokens
- Buzz private keys or auth tags
- TLS private keys generated for a real deployment
- SSH private keys
- database passwords
- Hermes runtime databases, sessions or auth state
- xySat `config.json`
- xySat auth tokens
- xyOps bootstrap tokens
- xyOps runtime secret keys or persisted security-sensitive configuration

The repository contains source configuration and safe examples only. Persistent runtime state belongs under `/opt/docker/runtime`.
