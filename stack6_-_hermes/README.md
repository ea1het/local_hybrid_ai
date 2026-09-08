# Stack6 - Hermes Agent

Stack6 provides the agent/orchestration layer for `local_hybrid_ai`.

Its responsibilities are deliberately split:

- **Hermes Agent** — reasoning, tools, messaging and native deferred scheduling;
- **hermes-sandbox** — isolated SSH execution environment;
- **hermes-memory-sync** — deterministic Git synchronization of `MEMORY.md` / `USER.md`;
- **hermes-sandbox-cleanup** — audit, lifecycle tracking and cleanup of ephemeral sandbox work;
- **Git-backed memory** — persistent Hermes long-term memory.

> Hermes owns intelligent work. Small deterministic sidecars own mechanical maintenance.

## Architecture

```text
User / Telegram
      |
      v
    Hermes
      |-- LiteLLM -> local/cloud policy boundary
      |-- native Cron -> future fresh AIAgent runs
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

## Hermes native Cron

Deferred intelligent work uses Hermes' native `cronjob` capability. Stack6 does not implement a custom scheduler API.

The managed Hermes system prompt contains two policies:

- `deferred_work_policy` — use native cron when work genuinely depends on a future time/event, and make future prompts self-contained;
- `sandbox_lifecycle_policy` — the sandbox is ephemeral scratch space; anything needed by future work must be persisted to durable storage outside the sandbox.

Durable storage is intentionally described generically until a specific backend is integrated.

## Git-backed memory

The memory working tree remains:

```text
/opt/docker/runtime/service_-_hermes-memory/data/
├── .git/
├── MEMORY.md
└── USER.md
```

`04-gitmem.sh` prepares and validates this working tree. It never pulls, merges, rebases, commits or pushes.

`hermes-memory-sync` performs periodic synchronization every 900 seconds by default:

```dotenv
MEMORY_SYNC_INTERVAL_SECONDS=900
```

The sidecar:

- accepts dirty changes only in `MEMORY.md` and `USER.md`;
- fetches before changing history;
- permits fast-forward only when remote is ahead and local is clean;
- commits/pushes local memory changes;
- refuses automatic merge/rebase on ambiguous divergence;
- never force-pushes;
- verifies local and remote heads match after success;
- uses a dedicated SSH identity under `service_-_hermes-memory-sync/ssh`.

`05-maintenance-sidecars.sh` validates that dedicated SSH identity and prepares sandbox lifecycle state. It does not create, copy or replace credentials.

## Sandbox lifecycle

The sandbox is explicitly **scratch space, not storage**.

Persistent runtime:

```text
/opt/docker/runtime/service_-_hermes-sandbox/
├── config/
├── data/
│   ├── home/
│   ├── workspace/
│   └── state/
│       └── state.db
└── logs/
```

The lifecycle database belongs to the sandbox generation, not to the cleanup sidecar.

Before `sshd` starts, `hermes-sandbox` initializes or validates `state.db`:

- SQLite integrity check must pass;
- schema/generation metadata must be valid;
- `.sandbox-generation` must exist and match the database generation ID;
- the first generation captures existing top-level workspace objects as protected baseline;
- `.cleanup-quarantine` is protected;
- a normal container restart preserves the generation and database;
- corrupt/incomplete state fails closed and directs the operator to `02-cleanup.sh --reset-sandbox`.

### Cleanup policy

Defaults:

```dotenv
SANDBOX_CLEANUP_RETENTION_DAYS=7
SANDBOX_CLEANUP_QUARANTINE_DAYS=1
SANDBOX_CLEANUP_DB_RETENTION_DAYS=90
SANDBOX_CLEANUP_SWEEP_HOUR=3
SANDBOX_CLEANUP_SWEEP_MINUTE=30
```

`hermes-sandbox-cleanup`:

- has no network (`network_mode: none`);
- watches `/workspace` with inotify;
- reconciles the top-level filesystem during every sweep so missed events do not break accounting;
- records first/last activity in SQLite;
- treats post-baseline top-level objects as disposable units;
- quarantines objects inactive beyond the retention period;
- deletes quarantined objects after the grace period;
- keeps deleted DB records for the configured audit retention;
- runs WAL checkpoint / incremental vacuum maintenance;
- performs audit logging during each sweep.

The cleaner does not attempt to preserve files merely because Hermes might want them later. The contract is the opposite: if Hermes needs an artifact later, Hermes must persist it outside the sandbox.

## Sandbox generation reset

Fast recovery from a corrupted lifecycle database is:

```bash
sudo ./02-cleanup.sh --reset-sandbox
```

This mode requires Hermes, `hermes-sandbox` and `hermes-sandbox-cleanup` to be stopped. It intentionally does **not** require removing Stack6 `.lock`.

It destroys only the current sandbox generation:

```text
sandbox workspace contents
sandbox data/state contents (including state.db)
```

It preserves:

```text
sandbox home / authorized_keys
sandbox host identity
Hermes runtime/session/auth state
Git-backed memory
managed configuration
```

The next sandbox boot creates a new generation and a fresh `state.db`.

## Runtime layout

```text
/opt/docker/runtime/
├── service_-_hermes/
├── service_-_hermes-memory/
├── service_-_hermes-memory-sync/
│   └── ssh/
└── service_-_hermes-sandbox/
    └── data/
        ├── home/
        ├── workspace/
        └── state/
```

The cleanup sidecar intentionally owns no separate persistent runtime directory; its durable state is the sandbox generation database.

## Deployment

After creating/updating the operational `.env`, provision the dedicated memory-sync SSH identity under `service_-_hermes-memory-sync/ssh` and authorize it for the configured Gitea memory repository. Then:

```bash
cd /opt/docker/stacks/stack6_-_hermes
sudo ./01-prepare.sh
sudo ./04-gitmem.sh
sudo ./05-maintenance-sidecars.sh

docker compose config --quiet
docker compose up -d --build
docker compose ps
```

For the validated Hermes version, retain the terminal-timeout workaround while the upstream issue remains unresolved:

```bash
sudo ./03-temporary-fix-issue-74116-terminal-timeout.sh
```

Expected services:

```text
hermes
hermes-sandbox
hermes-memory-sync
hermes-sandbox-cleanup
```

## Security boundaries

None of the Stack6 services receives `/var/run/docker.sock` or privileged mode.

`hermes-sandbox` is isolated on `hermes-exec` and has no `redlocal` access.

`hermes-memory-sync` receives only:

- the Git-backed memory worktree (RW);
- its dedicated SSH identity (RO);
- `redlocal` connectivity required to reach Gitea.

`hermes-sandbox-cleanup` receives only:

- sandbox workspace (RW);
- sandbox lifecycle state (RW);
- no network.

Do not commit operational `.env`, private SSH keys, Hermes/LiteLLM/Telegram credentials, runtime databases or other deployment secrets.

## Validated boundaries

The deployed host has validated:

```text
Hermes -> LiteLLM -> local inference
Hermes -> SSH -> hermes-sandbox
Hermes -> SearXNG / Firecrawl
Hermes -> Git-backed memory
Hermes native Cron -> future AIAgent run
hermes-memory-sync -> Gitea fetch/write authorization
hermes-sandbox -> state.db generation initialization and restart persistence
hermes-sandbox-cleanup -> inotify / audit / quarantine / deletion lifecycle
02-cleanup.sh --reset-sandbox -> fresh generation recovery
```
