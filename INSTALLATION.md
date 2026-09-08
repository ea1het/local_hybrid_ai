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
└── runtime/
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
    ├── service_-_hermes-memory/
    ├── service_-_hermes-memory-sync/
    └── service_-_hermes-sandbox/
```

`dockhand_data` remains an external Docker volume.

## Environment contract

Every operational stack uses:

```dotenv
STACKS_ROOT=/opt/docker/stacks
BASE_PATH=/opt/docker/runtime
```

`STACKS_ROOT` is source only. `BASE_PATH` is persistent runtime only.

Operational `.env` files contain deployment-specific values and secrets and must not be committed.

## Clean installation

```bash
sudo mkdir -p /opt/docker
cd /opt/docker
sudo git clone https://github.com/ea1het/local_hybrid_ai.git stacks
cd /opt/docker/stacks
```

The normal deployment order is:

1. Stack1 — HAProxy and static web
2. Stack2 — SearXNG and Firecrawl
3. Stack3 — LiteLLM
4. Stack4 — Gitea
5. Stack5 — Dockhand
6. Stack6 — Hermes, native Cron, isolated sandbox and maintenance sidecars

### Stack1

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

### Stack2

```bash
cd /opt/docker/stacks/stack2_-_searxng_firecrawl
cp .env.example .env
# edit .env
sudo ./01-prepare.sh
docker compose up -d
```

### Stack3

```bash
cd /opt/docker/stacks/stack3_-_litellm
cp .env.example .env
# edit .env
sudo ./01-prepare.sh
sudo ./02-postgres.sh
docker compose up -d --force-recreate litellm
```

LiteLLM is both the model-routing boundary and the shared MCP gateway.

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

Create the operational `.env` from `.env.template` and configure the deployment-specific values and secrets.

Important non-secret defaults include:

```dotenv
STACKS_ROOT=/opt/docker/stacks
BASE_PATH=/opt/docker/runtime
HERMES_IMAGE=nousresearch/hermes-agent
HERMES_VERSION=v2026.8.31
HERMES_MEMORY_SERVICE=service_-_hermes-memory
MEMORY_SYNC_SERVICE=service_-_hermes-memory-sync
MEMORY_SYNC_INTERVAL_SECONDS=900
SANDBOX_CLEANUP_RETENTION_DAYS=7
SANDBOX_CLEANUP_QUARANTINE_DAYS=1
SANDBOX_CLEANUP_DB_RETENTION_DAYS=90
SANDBOX_CLEANUP_SWEEP_HOUR=3
SANDBOX_CLEANUP_SWEEP_MINUTE=30
```

The configured private Git memory repository must already contain regular files:

```text
MEMORY.md
USER.md
```

Prepare in this order:

```bash
cd /opt/docker/stacks/stack6_-_hermes
sudo ./01-prepare.sh
sudo ./04-gitmem.sh
sudo ./05-maintenance-sidecars.sh

docker compose config --quiet
docker compose up -d --build
docker compose ps
```

`04-gitmem.sh` prepares and validates the memory working tree but does not modify Git history.

`05-maintenance-sidecars.sh` prepares the dedicated memory-sync SSH runtime and the sandbox lifecycle-state directory. During migration from the retired xySat deployment, it can copy the already-authorized xySat SSH identity into `service_-_hermes-memory-sync/ssh`; it does not delete the legacy runtime.

Expected services are:

```text
hermes
hermes-sandbox
hermes-memory-sync
hermes-sandbox-cleanup
```

For the currently validated Hermes version, retain the terminal-timeout workaround while required:

```bash
sudo ./03-temporary-fix-issue-74116-terminal-timeout.sh
```

## Scheduling policy

Deferred intelligent work uses Hermes native Cron. There is no separate scheduler stack.

The managed Hermes prompt teaches the agent to:

- defer work only when a future time/event genuinely matters;
- create self-contained future cron tasks;
- avoid duplicate/meaningless scheduling;
- treat `/workspace` as ephemeral scratch space;
- persist artifacts required by future work to durable storage outside the sandbox.

The durable-storage backend is intentionally generic until a specific integration is selected.

## Memory synchronization

`hermes-memory-sync` runs every 15 minutes by default and performs conservative Git synchronization of `MEMORY.md` and `USER.md`.

It refuses automatic conflict resolution and never force-pushes.

Its dedicated SSH identity lives under:

```text
/opt/docker/runtime/service_-_hermes-memory-sync/ssh/
```

## Sandbox lifecycle

The sandbox owns a persistent lifecycle ledger:

```text
/opt/docker/runtime/service_-_hermes-sandbox/data/state/state.db
```

The database is initialized or validated before `sshd` starts.

The cleanup sidecar watches the workspace with inotify and performs a daily sweep. New post-baseline top-level objects are disposable. After the configured inactivity period they are quarantined, then deleted after the grace period.

The cleanup sidecar has no network access.

### Fast sandbox repair

If `state.db` is corrupt or the sandbox generation must be discarded:

1. Stop Hermes, the sandbox and cleanup sidecar.
2. Run:

```bash
sudo ./02-cleanup.sh --reset-sandbox
```

This deletes only the current sandbox workspace generation and its lifecycle DB. It preserves Hermes state, Git-backed memory, sandbox home/SSH identity and managed configuration. The next sandbox boot creates a new generation and database.

## Retiring legacy xyOps / xySat runtime

Do **not** delete the old runtime before validating the new sidecars.

First confirm:

```text
hermes-memory-sync -> successful fetch/commit/push -> Gitea
hermes-sandbox -> state.db initialized and integrity-check passes
hermes-sandbox-cleanup -> watcher + sweep healthy
Hermes native Cron -> real future task executes
```

Only after that validation may the old runtime be removed deliberately:

```text
/opt/docker/runtime/service_-_xyops/
/opt/docker/runtime/service_-_xysat/
```

The source repository no longer contains `stack7_-_xyops` and HAProxy no longer exposes `xyops.casa.lan`.

## Deployment state

Preparation scripts create local `.lock` files only after their audits succeed. Operational `.env` and `.lock` files are deployment state, not source configuration.

Persistent application data belongs below `/opt/docker/runtime`.

## Updating the checkout

Before updating:

```bash
cd /opt/docker/stacks
git status --short
git branch --show-current
```

After pulling a change, use the affected stack's documented prepare/recreate process. `docker restart` does not apply changed container environment or rebuilt images.

## Security boundary

Never commit real values for:

- operational `.env` files
- LiteLLM inference/MCP keys
- local/cloud model API tokens
- Telegram/Buzz credentials
- TLS private keys
- SSH private keys
- database passwords
- Hermes runtime databases, sessions or auth state
- memory-sync SSH identity
- sandbox lifecycle databases

The repository contains source configuration and safe templates only.
