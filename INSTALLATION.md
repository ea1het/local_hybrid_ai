# Installation and lifecycle

This document describes the deployment contract for `local_hybrid_ai`. The root common installer consumes the same manifest/dependency/capability model as the stacks; manual stack commands remain useful for bounded maintenance and diagnosis.

## 1. Permanent layout

```text
/opt/docker/
├── stacks/                  # one Git working tree
│   ├── .git/
│   ├── .env                 # operational, secret, ignored by Git
│   ├── .env.template        # tracked variable contract
│   ├── install.sh           # common installer entry point
│   ├── install.py           # dependency-driven orchestrator
│   ├── installer/
│   │   └── lifecycle.json   # stack-owned lifecycle command registry
│   └── stack0...stack6/
└── runtime/                 # persistent mutable state, never Git source
```

```dotenv
STACKS_ROOT=/opt/docker/stacks
BASE_PATH=/opt/docker/runtime
NETWORK_NAME=redlocal
```

Stack0 manages each application stack's `.env -> ../.env` compatibility link. The operational root `.env` must be `root:root 0600` on the reference deployment.

## 2. Dependency and capability model

```mermaid
flowchart TB
    S0[0 Platform] --> S1[1 HAProxy/Web]
    S0 --> S2[2 Search/Extract]
    S0 --> S3[3 LiteLLM]
    S0 --> S4[4 Gitea]
    S0 --> S5[5 Dockhand]
    S0 --> S6[6 Hermes]
    S3 -->|required AI capabilities| S6
    S2 -.->|optional web capabilities| S6
    S4 -.->|optional git.remote| S6
```

All application stacks require Stack0. Stack6 requires Stack3. Stack2 and Stack4 are optional for Stack6.

The manifest registry validates dependency cycles, ownership collisions and capability contracts. Useful commands:

```bash
python3 stack0_-_platform/manifests.py validate
python3 stack0_-_platform/manifests.py validate --target
python3 stack0_-_platform/manifests.py list
python3 stack0_-_platform/manifests.py plan 6
python3 stack0_-_platform/manifests.py plan all
```

`plan 6` resolves the minimum required order as Stack0 -> Stack3 -> Stack6.

## 3. Common installer

The root installer is deliberately thin. `manifests.py` decides **which stacks and dependency order** are required; `installer/lifecycle.json` maps each stack to its own lifecycle entry points. The installer does not duplicate stack implementation.

```mermaid
flowchart LR
    CLI[install.sh selectors] --> M[manifest resolver]
    M --> P[dependency plan]
    P --> L[lifecycle registry]
    L --> S[stack-owned scripts / Compose]
    S --> V[verification]
```

Inspect before execution:

```bash
./install.sh 6 --plan
./install.sh 6 --dry-run
./install.sh 2 4 6 --dry-run
./install.sh all --plan
```

Real execution requires an explicit acknowledgement:

```bash
sudo ./install.sh 6 --yes
sudo ./install.sh all --yes
```

Selectors accepted by the installer are the same selectors accepted by the manifest planner: numeric IDs, `stackN`, exact stack directory names, or `all`.

`--plan` and `--dry-run` never execute lifecycle actions. `--dry-run` prints the exact actions that real execution would run. `--target` resolves `target_requires` instead of the current dependency graph.

The installer detects PREPARED state from `.lock` and therefore does not remove locks or re-run PREPARE merely to converge an existing stack. Deployment commands remain idempotent/convergent stack-owned operations. Optional Stack6 capabilities are reconciled by Stack6 after deployment.

Safety properties of the common installer:

- never rewrites the operational `.env`;
- never deletes `.lock` automatically;
- never runs Docker prune or `docker compose down -v`;
- never resets runtime state;
- never hard-codes Stack6 -> Stack3 dependency logic;
- does not perform the legacy Stack3 PostgreSQL migration;
- stops on the first failed lifecycle action and reports that action;
- keeps stack implementation inside the owning stack.

The lifecycle registry is intentionally declarative but is **not** a second dependency graph. Dependencies, optional relationships, capabilities and ownership stay in `manifest.json`.

## 4. Lifecycle states

```mermaid
stateDiagram-v2
    [*] --> Source
    Source --> Prepared: 01-prepare.sh
    Prepared --> Running: stack start/provision
    Running --> Reconciled: optional capabilities reconciled
    Reconciled --> Running: provider/intent changes
```

`.lock` means **PREPARED only**. It does not mean deployed, running, healthy or reconciled.

PREPARE owns creation/validation of resources belonging to that stack. RECONCILE is a separate repeatable operation for optional capabilities and must not require deleting `.lock`.

## 5. Clean installation

Clone once and create the central environment:

```bash
sudo mkdir -p /opt/docker
cd /opt/docker
sudo git clone https://github.com/ea1het/local_hybrid_ai.git stacks
cd /opt/docker/stacks
sudo cp .env.template .env
sudo chown root:root .env
sudo chmod 0600 .env
sudo editor .env
```

Then inspect and run the common installer. A complete installation is:

```bash
./install.sh all --plan
sudo ./install.sh all --yes
```

A minimal Hermes installation is dependency-resolved automatically:

```bash
./install.sh 6 --plan
sudo ./install.sh 6 --yes
```

The resolved required plan is Stack0 -> Stack3 -> Stack6. Numeric order `0,1,2,3,4,5,6` remains convenient for a full deployment but is not the dependency model.

## 6. Manual stack deployment procedures

These remain authoritative bounded operations when maintaining one stack directly.

### Stack1 — HAProxy + static web

```bash
cd /opt/docker/stacks/stack1_-_haproxy_web
sudo ./01-prepare.sh
docker compose up -d
docker compose ps
```

Stack1 consumes Stack0 PKI read-only. Backends are optional from Stack1's dependency perspective; HAProxy can start while they are absent.

### Stack2 — SearXNG + Firecrawl

```bash
cd /opt/docker/stacks/stack2_-_searxng_firecrawl
sudo ./01-prepare.sh
docker compose up -d
docker compose ps
```

Stack2 provides `web.search` and `web.extract`. It owns SearXNG, Firecrawl API/Playwright, Redis, RabbitMQ and its own PostgreSQL persistence. It never creates `redlocal`.

### Stack3 — LiteLLM + dedicated PostgreSQL

```bash
cd /opt/docker/stacks/stack3_-_litellm
sudo ./01-prepare.sh
sudo ./02-postgres.sh
docker compose up -d litellm
docker compose ps
```

Stack3 provides `ai.gateway` and `ai.mcp-gateway`. It owns `litellm-postgres` and `${BASE_PATH}/service_-_litellm-postgres`.

**PGDATA safety:** on an existing deployment, PREPARE validates and preserves the existing PostgreSQL data directory. It does not change its owner, mode or inode. On a new empty runtime the official PostgreSQL container performs database initialization. Never recursively `chown` an existing cluster as a routine repair.

`LITELLM_SALT_KEY` and existing database identities must be preserved.

`90-migrate-postgres-from-stack2.sh` is a one-time legacy migration helper only. Do not run it on a clean installation and do not rerun it after migration has succeeded. The common installer never invokes it.

### Stack4 — Gitea + runner

```bash
cd /opt/docker/stacks/stack4_-_gitea
sudo ./01-prepare.sh
sudo ./02-run.sh
```

Stack4 provides `git.remote` and `git.runner`. It owns the Gitea/runner runtimes and the persistent runner registration secret. Existing Gitea data, runner `.runner` identity and registration token are preserved.

### Stack5 — Dockhand

```bash
cd /opt/docker/stacks/stack5_-_dockhand
sudo ./01-prepare.sh
docker compose up -d
docker compose ps
```

Stack5 owns the external Docker volume `dockhand_data`. PREPARE creates it only if absent and never removes/recreates an existing volume.

### Stack6 — Hermes

Minimum dependencies: Stack0 + Stack3.

```bash
cd /opt/docker/stacks/stack6_-_hermes
sudo ./01-prepare.sh
sudo ./04-gitmem.sh
sudo ./05-maintenance-sidecars.sh
docker compose config --quiet
docker compose up -d --build
sudo ./06-reconcile-capabilities.sh --restart
docker compose ps
```

`04-gitmem.sh` is an explicit adoption/validation operation and is not run automatically by the common installer: adoption can require stopped Hermes and operator knowledge of local/remote memory state. `05-maintenance-sidecars.sh` prepares/validates maintenance prerequisites. `06-reconcile-capabilities.sh` is the repeatable capability reconciliation layer.

The temporary terminal-timeout workaround for the validated Hermes version remains:

```bash
sudo ./03-temporary-fix-issue-74116-terminal-timeout.sh
```

## 7. Incremental optional capabilities

### Add local web after Hermes is already running

Deploy Stack2, then reconcile Stack6. When using the common installer and Stack6 is part of the requested plan, reconciliation is already the final Stack6 deployment action. If Stack2 alone is installed later, explicitly reconcile the already-running consumer:

```bash
sudo ./install.sh 2 --yes
cd /opt/docker/stacks/stack6_-_hermes
sudo ./06-reconcile-capabilities.sh --restart
```

When both SearXNG and Firecrawl are running on `redlocal`, the managed Hermes configuration enables web tooling. If either provider is unavailable, web remains explicitly disabled. There is no external-provider fallback from this mechanism.

### Git-backed memory intent

Git memory is not enabled merely because Gitea exists. The operator must explicitly persist intent:

```bash
cd /opt/docker/stacks/stack6_-_hermes
sudo ./06-reconcile-capabilities.sh --enable-git-memory
```

Disable it with:

```bash
sudo ./06-reconcile-capabilities.sh --disable-git-memory
```

Without either flag, the previous desired state is preserved. A new deployment defaults to disabled.

If Git memory is enabled but Gitea becomes unavailable, reconciliation stops only `hermes-memory-sync`; it preserves the memory worktree, SSH identity and desired state. When the provider returns, reconciliation can resume the sidecar after clean local/remote equality checks.

## 8. Network/security boundaries

```mermaid
flowchart LR
    RED[redlocal] --- H[Hermes]
    RED --- LL[LiteLLM]
    RED --- G[Gitea]
    RED --- SX[SearXNG/Firecrawl]
    H --- EXEC[hermes-exec]
    EXEC --- SB[Sandbox]
    CLEAN[Sandbox cleanup] -->|network_mode: none| NONE[No network]
```

The sandbox is not attached to `redlocal`, has no Docker socket and is not privileged. Hermes reaches it only over SSH on `hermes-exec`. The cleanup sidecar has no network.

## 9. Sandbox lifecycle and recovery

Generation identity is stored in both:

```text
${BASE_PATH}/service_-_hermes-sandbox/data/workspace/.sandbox-generation
${BASE_PATH}/service_-_hermes-sandbox/data/state/state.db
```

They must agree. Normal restarts preserve the generation. For corrupt/mismatched lifecycle state, use the bounded reset documented by Stack6. Never turn sandbox recovery into a whole-platform wipe.

## 10. Updating an existing deployment

Git updates must not overwrite deployment state:

```bash
cd /opt/docker/stacks
git status --short
git branch --show-current
git fetch origin main
git merge --ff-only origin/main
```

The root `.env`, stack `.env` symlinks, `.lock` files and `/opt/docker/runtime` are outside tracked source changes.

After an update, use the common installer for dependency-aware convergence or the affected stack's documented lifecycle for bounded maintenance. Do not delete `.lock` merely to activate an optional capability; use reconciliation. A plain `docker restart` does not apply changed Compose environment/mounts.

## 11. Re-preparation

Removing a `.lock` and rerunning PREPARE is an explicit maintenance action, not a normal update primitive. Before doing so, understand what the stack's PREPARE manages and preserve persistent identities.

Validated atomic PREPARE behavior includes preserving bind-directory identity where required, persistent databases/volumes, generated secrets and existing runtime data. Stack3 specifically preserves existing PGDATA owner/mode/inode.

## 12. Secrets and persistent identities

Never commit or casually rotate:

- root operational `.env`;
- LiteLLM inference/MCP keys and `LITELLM_SALT_KEY`;
- provider API tokens;
- Telegram/Buzz credentials;
- TLS private keys;
- SSH private keys;
- database passwords;
- Gitea persistent secrets and runner identity/token;
- Hermes runtime databases/sessions/auth state;
- memory-sync SSH identity;
- sandbox lifecycle database/generation state.

The repository contains source configuration and `.env.template`, never production secret values.
