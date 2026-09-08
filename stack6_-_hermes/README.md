# Stack6 - Hermes Agent

Stack6 provides the agent/orchestration layer for `local_hybrid_ai`.

Its responsibilities are deliberately split:

- **Hermes Agent** — reasoning, tools, messaging and native deferred scheduling;
- **hermes-sandbox** — isolated SSH execution environment;
- **hermes-memory-sync** — conservative Git synchronization of `MEMORY.md` / `USER.md`;
- **hermes-sandbox-cleanup** — lifecycle tracking and cleanup of ephemeral sandbox work;
- **Git-backed memory** — persistent Hermes long-term memory.

> Hermes owns intelligent work. Small deterministic sidecars own mechanical maintenance.

## Service map

| Service | Networks | Persistent state | Purpose |
|---|---|---|---|
| `hermes` | `redlocal`, `hermes-exec` | `service_-_hermes`, Git memory mount | Agent runtime, tools, messaging, native Cron |
| `hermes-sandbox` | `hermes-exec` | `service_-_hermes-sandbox` | Isolated SSH execution |
| `hermes-memory-sync` | `redlocal` | memory worktree + dedicated SSH identity | Git synchronization |
| `hermes-sandbox-cleanup` | none | sandbox workspace + lifecycle DB | Retention, quarantine and cleanup |

No Stack6 service receives the Docker socket or privileged mode.

## Architecture

```text
User / Telegram / Buzz
          |
          v
        Hermes
          |-- LiteLLM -> model policy -> local/cloud inference
          |-- LiteLLM MCP Gateway -> upstream MCP servers
          |-- native Cron -> future fresh agent runs
          |-- SSH -> hermes-sandbox
          |-- memory -> service_-_hermes-memory/data
                           ^
                           |
                  hermes-memory-sync -> Gitea

hermes-sandbox workspace
          ^
          |
hermes-sandbox-cleanup
  inotify + SQLite + retention/quarantine
```

## Native Cron

Deferred intelligent work uses Hermes' native `cronjob` capability. Stack6 does not implement a custom scheduler API.

Cron runs are fresh agent sessions. They load persistent memory, but they do not inherit the conversation that created the job. A scheduled prompt therefore must be self-contained.

The managed Hermes system prompt contains two relevant policies:

- `deferred_work_policy` — defer only genuinely future-dependent work, make future prompts self-contained and avoid duplicate jobs;
- `sandbox_lifecycle_policy` — the sandbox is ephemeral scratch space; anything required later must be persisted to durable storage.

A current failure is not, by itself, a reason to create a Cron job.

## Git-backed memory

The memory working tree is:

```text
/opt/docker/runtime/service_-_hermes-memory/data/
├── .git/
├── MEMORY.md
└── USER.md
```

`04-gitmem.sh` prepares and validates this working tree. It does not pull, merge, rebase, commit or push.

`hermes-memory-sync` performs the periodic synchronization every 900 seconds by default:

```dotenv
MEMORY_SYNC_INTERVAL_SECONDS=900
```

The sidecar:

- accepts dirty changes only in `MEMORY.md` and `USER.md`;
- fetches before changing local history;
- permits fast-forward only when remote is ahead and local state is clean;
- commits/pushes valid local memory changes;
- refuses automatic merge/rebase on divergence;
- never force-pushes;
- checks that local and remote heads match after success.

### Dedicated memory-sync SSH identity

Runtime path:

```text
/opt/docker/runtime/service_-_hermes-memory-sync/ssh/
├── id_ed25519
├── known_hosts
└── ssh_config
```

`05-maintenance-sidecars.sh` validates this identity and the sandbox lifecycle-state directory. It does not create, copy or replace credentials.

Provision and authorize the identity for the configured Gitea memory repository before running the script.

## Sandbox lifecycle

The sandbox is explicitly **scratch space, not storage**.

Persistent runtime:

```text
/opt/docker/runtime/service_-_hermes-sandbox/
├── config/
├── data/
│   ├── home/
│   ├── workspace/
│   │   ├── .sandbox-generation
│   │   └── .cleanup-quarantine/
│   └── state/
│       └── state.db
└── logs/
```

The logical sandbox generation is represented by both:

```text
/workspace/.sandbox-generation
/var/lib/hermes-sandbox-state/state.db
```

The marker generation ID and SQLite metadata generation ID must match.

Before `sshd` starts, `hermes-sandbox` validates:

- `state.db` is a regular non-symlink file when present;
- SQLite integrity passes;
- schema metadata is supported;
- `.sandbox-generation` is a regular non-symlink file;
- the marker is non-empty;
- marker generation equals database generation.

If no state exists, first boot of a new generation:

1. creates a new generation ID;
2. initializes SQLite lifecycle state;
3. captures existing top-level workspace objects as the protected baseline;
4. protects `.sandbox-generation` and `.cleanup-quarantine`;
5. starts `sshd` only after state initialization succeeds.

A normal restart preserves the generation.

If marker/database state is incomplete, corrupt or mismatched, startup fails closed and instructs the operator to use `02-cleanup.sh --reset-sandbox`.

## Cleanup policy

Defaults:

```dotenv
SANDBOX_CLEANUP_RETENTION_DAYS=7
SANDBOX_CLEANUP_QUARANTINE_DAYS=1
SANDBOX_CLEANUP_DB_RETENTION_DAYS=90
SANDBOX_CLEANUP_SWEEP_HOUR=3
SANDBOX_CLEANUP_SWEEP_MINUTE=30
```

`hermes-sandbox-cleanup`:

- uses `network_mode: none`;
- validates the sandbox generation marker against `state.db` before operating;
- watches `/workspace` recursively with inotify;
- records activity at top-level object granularity;
- reconciles actual top-level filesystem state during every sweep;
- treats post-baseline objects as disposable;
- quarantines objects inactive beyond retention;
- waits through the configured quarantine grace period;
- deletes matching quarantined objects safely;
- retains deleted DB records for the configured audit period;
- performs WAL checkpoint / incremental vacuum maintenance;
- emits audit/sweep logs.

Cleanup intentionally does not preserve an artifact merely because Hermes might want it later. The contract is the opposite: Hermes must persist anything needed later before finishing the current run.

## Bounded sandbox recovery

Fast recovery from a corrupt or inconsistent sandbox generation is:

```bash
cd /opt/docker/stacks/stack6_-_hermes
docker compose stop hermes hermes-sandbox hermes-sandbox-cleanup
sudo ./02-cleanup.sh --reset-sandbox --yes
docker compose up -d hermes-sandbox hermes hermes-sandbox-cleanup
```

This mode intentionally works without removing Stack6 `.lock`.

It destroys only:

```text
sandbox workspace contents
sandbox data/state contents
```

It preserves:

```text
sandbox home / authorized_keys
sandbox host identity
Hermes runtime/session/auth state
Git-backed memory
managed configuration
memory-sync SSH identity
```

The next sandbox boot creates a fresh logical generation.

## Runtime layout

```text
/opt/docker/runtime/
├── service_-_hermes/
├── service_-_hermes-memory/
├── service_-_hermes-memory-sync/
│   └── ssh/
└── service_-_hermes-sandbox/
    ├── config/
    ├── data/
    │   ├── home/
    │   ├── workspace/
    │   └── state/
    └── logs/
```

`hermes-sandbox-cleanup` intentionally owns no separate persistent runtime directory. Its durable state belongs to the sandbox generation database.

## Deployment

Create/update the operational `.env`, provision the dedicated memory-sync SSH identity, and then run:

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

For the validated Hermes version, retain the terminal-timeout workaround while the upstream issue remains unresolved:

```bash
sudo ./03-temporary-fix-issue-74116-terminal-timeout.sh
```

## Network and security boundaries

`hermes` is attached to `redlocal` and `hermes-exec`.

`hermes-sandbox` is attached only to `hermes-exec`; it has no `redlocal` access.

`hermes-memory-sync` has `redlocal` connectivity only because it must reach Gitea. Its mounts are limited to the Git-backed memory working tree and its dedicated SSH identity.

`hermes-sandbox-cleanup` receives only the sandbox workspace and lifecycle state and has no network.

Do not commit operational `.env`, private SSH keys, Hermes/LiteLLM/Telegram/Buzz credentials, runtime databases or other deployment secrets.

## Validated boundaries

The reference deployment has validated:

```text
Hermes -> LiteLLM -> local inference
Hermes -> SSH -> hermes-sandbox
Hermes -> SearXNG / Firecrawl
Hermes native Cron -> real one-shot future agent run
hermes-memory-sync -> Gitea fetch + write authorization
hermes-sandbox -> generation initialization and restart persistence
hermes-sandbox-cleanup -> inotify / audit / quarantine / deletion
02-cleanup.sh --reset-sandbox -> fresh generation recovery
```

The current deployed architecture has no dependency on a standalone scheduler runtime.
