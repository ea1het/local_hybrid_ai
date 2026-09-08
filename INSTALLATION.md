# Installation

This document describes the permanent installation layout and deployment flow for `local_hybrid_ai`.

The repository is deployed as one Git working tree. Mutable application state, credentials, databases and runtime-generated files live outside that checkout.

## Filesystem contract

```text
/opt/docker/
├── stacks/                  # Git checkout / source only
│   ├── .git/
│   ├── .env                 # operational deployment environment, NOT Git
│   ├── .env.template        # tracked central variable contract
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
    ├── service_-_hermes-memory/
    ├── service_-_hermes-memory-sync/
    └── service_-_hermes-sandbox/
```

`dockhand_data` remains an external Docker volume.

The shared deployment context remains:

```dotenv
STACKS_ROOT=/opt/docker/stacks
BASE_PATH=/opt/docker/runtime
```

`STACKS_ROOT` is Git-managed source. `BASE_PATH` is mutable persistent state.

## Central environment contract

The deployment now has one operational environment file:

```text
/opt/docker/stacks/.env
```

and one tracked reference template:

```text
/opt/docker/stacks/.env.template
```

The root `.env.template` is the single documented variable contract for all six stacks. Variables are grouped by stack and document their current consumers, secret status and lifecycle expectations.

The operational `.env` contains real values and secrets and must never be committed. Recommended ownership and permissions:

```text
root:root 0600
```

During the current manual-operation phase, each stack keeps a local symlink so the existing commands and scripts continue to resolve `.env` exactly where they already expect it:

```text
stack1_-_haproxy_web/.env       -> ../.env
stack2_-_searxng_firecrawl/.env -> ../.env
stack3_-_litellm/.env           -> ../.env
stack4_-_gitea/.env             -> ../.env
stack5_-_dockhand/.env          -> ../.env
stack6_-_hermes/.env            -> ../.env
```

These symlinks are deployment state and are not tracked in Git.

This preserves the existing manual workflow:

```bash
cd /opt/docker/stacks/stackN_...
docker compose up -d
```

while removing duplicated environment definitions from the repository.

## `.lock` contract

Every stack uses the same meaning:

```text
.lock = PREPARED
```

A `.lock` is created by that stack's `01-prepare.sh` only after successful preparation. It does **not** mean that later provisioning, startup, health checks or end-to-end validation have completed.

Later scripts may require `.lock`, but they do not own or create it.

## Architecture after the scheduler migration

The deployed platform contains six source stacks. There is no standalone scheduler stack.

Deferred intelligent work uses **Hermes native Cron**. Stack6 also contains two deterministic maintenance sidecars:

```text
hermes-memory-sync       -> conservative Git synchronization
hermes-sandbox-cleanup   -> sandbox lifecycle tracking and cleanup
```

The sandbox remains isolated from the infrastructure network and is reached by Hermes only over the private `hermes-exec` bridge using SSH.

## Clean installation

Clone the repository once:

```bash
sudo mkdir -p /opt/docker
cd /opt/docker
sudo git clone https://github.com/ea1het/local_hybrid_ai.git stacks
cd /opt/docker/stacks
```

Create the operational environment from the central template:

```bash
sudo cp .env.template .env
sudo chown root:root .env
sudo chmod 0600 .env
sudo editor .env
```

Create the stack-local compatibility symlinks:

```bash
for d in \
  stack1_-_haproxy_web \
  stack2_-_searxng_firecrawl \
  stack3_-_litellm \
  stack4_-_gitea \
  stack5_-_dockhand \
  stack6_-_hermes; do
  sudo ln -sfn ../.env "$d/.env"
done
```

Before preparing any stack, verify that all symlinks resolve to the root environment:

```bash
for d in stack*_*/; do
  test "$(readlink -f "${d}.env")" = "/opt/docker/stacks/.env" || exit 1
done
```

Normal deployment order:

1. Stack1 — HAProxy and static web
2. Stack2 — SearXNG and Firecrawl
3. Stack3 — LiteLLM
4. Stack4 — Gitea
5. Stack5 — Dockhand
6. Stack6 — Hermes, native Cron, isolated sandbox, Git-backed memory and maintenance sidecars

## Stack1 — HAProxy + web

```bash
cd /opt/docker/stacks/stack1_-_haproxy_web
cd config/haproxy
bash generate.txt
cd ../..
sudo ./01-prepare.sh
docker compose up -d
docker compose ps
```

HAProxy is the internal TLS/reverse-proxy boundary. Keep deployment-specific TLS private material outside Git.

## Stack2 — SearXNG + Firecrawl

```bash
cd /opt/docker/stacks/stack2_-_searxng_firecrawl
sudo ./01-prepare.sh
docker compose up -d
docker compose ps
```

## Stack3 — LiteLLM

```bash
cd /opt/docker/stacks/stack3_-_litellm
sudo ./01-prepare.sh
sudo ./02-postgres.sh
docker compose up -d --force-recreate litellm
docker compose ps
```

LiteLLM is both the model-routing boundary and the shared MCP gateway.

Applications and Hermes should target LiteLLM rather than provider-specific endpoints.

`02-postgres.sh` still reads the Stack2 `.env` path for the PostgreSQL administrative identity; because Stack2 `.env` is now a symlink, it resolves to the same central deployment environment.

## Stack4 — Gitea

```bash
cd /opt/docker/stacks/stack4_-_gitea
sudo ./01-prepare.sh
sudo ./02-run.sh
```

Gitea provides local Git infrastructure, including the Hermes memory repository.

## Stack5 — Dockhand

```bash
cd /opt/docker/stacks/stack5_-_dockhand
sudo ./01-prepare.sh
docker compose up -d
docker compose ps
```

## Stack6 — Hermes

Stack6 consumes its variables from the same root environment through `stack6_-_hermes/.env -> ../.env`.

Important non-secret defaults include:

```dotenv
STACKS_ROOT=/opt/docker/stacks
BASE_PATH=/opt/docker/runtime
NETWORK_NAME=redlocal
TZ=Europe/Madrid

HERMES_IMAGE=nousresearch/hermes-agent
HERMES_VERSION=v2026.8.31

HERMES_MEMORY_SERVICE=service_-_hermes-memory
MEMORY_SYNC_SERVICE=service_-_hermes-memory-sync
MEMORY_SYNC_INTERVAL_SECONDS=900

SANDBOX_SERVICE=service_-_hermes-sandbox
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

### Memory-sync SSH identity

`hermes-memory-sync` uses its own dedicated SSH material:

```text
/opt/docker/runtime/service_-_hermes-memory-sync/ssh/
├── id_ed25519
├── known_hosts
└── ssh_config
```

Provision and authorize that identity for the configured Gitea memory repository before running `05-maintenance-sidecars.sh`.

The preparation script validates this material. It does not create, copy or replace credentials.

### Stack6 preparation and start

```bash
cd /opt/docker/stacks/stack6_-_hermes
sudo ./01-prepare.sh
sudo ./04-gitmem.sh
sudo ./05-maintenance-sidecars.sh

docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Expected services:

```text
hermes
hermes-sandbox
hermes-memory-sync
hermes-sandbox-cleanup
```

`04-gitmem.sh` prepares and validates the Git-backed memory worktree but does not merge, rebase, commit or push.

`05-maintenance-sidecars.sh` validates the dedicated memory-sync SSH runtime and prepares the sandbox lifecycle-state directory.

### Temporary terminal-timeout workaround

For the currently validated Hermes version, retain the workaround while the upstream issue remains unresolved:

```bash
sudo ./03-temporary-fix-issue-74116-terminal-timeout.sh
```

## Hermes scheduling policy

Deferred intelligent work uses Hermes native Cron.

Scheduled jobs run in fresh agent sessions. A future job prompt therefore must be self-contained and include enough context to recover any persistent input it needs.

The managed Hermes prompt enforces two policies:

- `deferred_work_policy` — schedule only genuinely future-dependent work and avoid duplicate/meaningless jobs;
- `sandbox_lifecycle_policy` — never rely on scratch files surviving until a future run.

## Git-backed memory synchronization

The long-term memory worktree is:

```text
/opt/docker/runtime/service_-_hermes-memory/data/
├── .git/
├── MEMORY.md
└── USER.md
```

`hermes-memory-sync` runs every 15 minutes by default and uses conservative Git behavior:

- only `MEMORY.md` and `USER.md` may be dirty;
- remote-ahead + clean local state may fast-forward;
- local changes may be committed and pushed;
- divergence fails instead of auto-merging or rebasing;
- force-push is never used;
- local and remote heads are checked after synchronization.

## Sandbox lifecycle

The sandbox is scratch space, not durable storage.

Its generation state is represented by both:

```text
/opt/docker/runtime/service_-_hermes-sandbox/data/workspace/.sandbox-generation
/opt/docker/runtime/service_-_hermes-sandbox/data/state/state.db
```

The marker generation ID and SQLite generation metadata must match.

On first boot of a new generation, the sandbox initializes the database and protects the existing top-level workspace baseline before starting `sshd`.

A normal container restart preserves the same generation.

### Cleanup policy

`hermes-sandbox-cleanup` has no network access.

It watches `/workspace` with inotify, reconciles top-level state during sweeps, quarantines inactive post-baseline objects and removes them after the configured grace period.

Default retention:

```dotenv
SANDBOX_CLEANUP_RETENTION_DAYS=7
SANDBOX_CLEANUP_QUARANTINE_DAYS=1
SANDBOX_CLEANUP_DB_RETENTION_DAYS=90
SANDBOX_CLEANUP_SWEEP_HOUR=3
SANDBOX_CLEANUP_SWEEP_MINUTE=30
```

The cleaner validates the generation marker against `state.db` before operating.

## Fast sandbox recovery

If the lifecycle database or generation marker becomes corrupt or inconsistent:

```bash
cd /opt/docker/stacks/stack6_-_hermes
docker compose stop hermes hermes-sandbox hermes-sandbox-cleanup
sudo ./02-cleanup.sh --reset-sandbox --yes
docker compose up -d hermes-sandbox hermes hermes-sandbox-cleanup
```

`--reset-sandbox` removes only the current workspace generation and lifecycle state.

It preserves:

```text
Hermes runtime/session/auth state
Git-backed memory
sandbox home / authorized_keys
sandbox host identity
managed configuration
memory-sync SSH identity
```

The next sandbox boot creates a fresh generation.

## Network boundaries

The shared infrastructure network is `redlocal`.

Hermes is attached to both `redlocal` and the private `hermes-exec` bridge.

The sandbox is attached only to `hermes-exec`.

`hermes-memory-sync` uses `redlocal` to reach Gitea.

`hermes-sandbox-cleanup` uses `network_mode: none`.

No Stack6 service receives `/var/run/docker.sock` or privileged mode.

## Updating an existing deployment

Before updating:

```bash
cd /opt/docker/stacks
git status --short
git branch --show-current
git fetch origin
```

A healthy deployment checkout should have no tracked local modifications.

Then update the desired branch, for example:

```bash
git switch main
git pull --ff-only
```

The root `.env` and stack-local `.env` symlinks are deployment state and remain untouched by Git updates.

After pulling changes, use the affected stack's prepare/recreate procedure. A plain `docker restart` does not apply changed container environment or rebuilt images.

## Deployment state

Preparation scripts create local `.lock` files only after successful `01-prepare.sh` completion.

The root operational `.env`, stack-local `.env` symlinks, `.lock`, generated credentials, databases and service state are deployment data, not source configuration.

Persistent application data belongs below `/opt/docker/runtime`.

## Security boundary

Never commit real values for:

- the root operational `.env`;
- LiteLLM inference/MCP keys;
- provider API tokens;
- Telegram/Buzz credentials;
- TLS private keys;
- SSH private keys;
- database passwords;
- Hermes runtime databases, sessions or auth state;
- memory-sync SSH identity;
- sandbox lifecycle databases or generation state.

The repository contains source configuration and the safe central `.env.template` only.

## Reference deployment validation

The current six-stack architecture has been validated on the reference host for:

```text
LiteLLM -> local inference
Hermes -> LiteLLM -> local inference
Hermes -> SSH -> hermes-sandbox
Hermes -> SearXNG / Firecrawl
Hermes native Cron -> real one-shot future agent run
hermes-memory-sync -> Gitea fetch + write authorization
sandbox generation -> initialize + survive normal restart
sandbox cleanup -> inotify + audit + quarantine + deletion
--reset-sandbox -> fresh generation recovery
HAProxy -> current service routes
```
