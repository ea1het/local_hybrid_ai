# Stack7 - xyOps Scheduler

Stack7 provides the dedicated scheduling and operational-automation layer for the `local_hybrid_ai` platform.

It is intentionally separated into two components:

- **xyOps conductor**
  - Web UI
  - API
  - Scheduler
  - Job history
  - Persistent conductor state
  - Does not execute host jobs directly

- **xySat worker**
  - Dedicated job runner
  - Connects outbound to the conductor
  - Executes only explicitly approved scripts
  - Receives only explicitly approved filesystem mounts

The scheduling layer is deliberately designed so that:

> **A scheduler is not the Docker host, and a scheduler is not the Docker daemon.**

---

## Deployed versions

```dotenv
XYOPS_IMAGE=ghcr.io/pixlcore/xyops
XYOPS_VERSION=v1.0.96

XYSAT_IMAGE=ghcr.io/pixlcore/xysat
XYSAT_VERSION=v1.0.45
```

`01-prepare.sh` rejects `latest` for both components.

---

## Architecture

Human access and worker communication use different paths.

### Human / browser access

```text
Browser
  |
  | HTTPS
  v
https://xyops.casa.lan
  |
  v
HAProxy
  |
  | HTTP over redlocal
  v
xyops:5522
```

TLS terminates at HAProxy.

The xyOps application port is not published directly on the Docker host.

### xySat worker path

```text
xysat
  |
  | Docker DNS / redlocal
  v
xyops:5522
```

The worker does not use the LAN-facing hostname for conductor communication.

Its permanent conductor configuration is:

```text
host   = xyops
port   = 5522
secure = false
```

The enrolled configuration may also contain an external `hosts` entry such as `xyops.casa.lan`, but the deployment's active direct-worker path is the explicit Docker-internal `host=xyops` entry.

This distinction is intentional:

```text
Human access:
    https://xyops.casa.lan

Docker-internal worker access:
    http://xyops:5522
```

---

## Source and runtime layout

Stack source:

```text
/opt/docker/stacks/stack7_-_xyops/
```

Persistent runtime:

```text
/opt/docker/runtime/service_-_xyops/
/opt/docker/runtime/service_-_xysat/
```

The platform contract is:

```dotenv
STACKS_ROOT=/opt/docker/stacks
BASE_PATH=/opt/docker/runtime
```

`STACKS_ROOT` contains source / Git-controlled definitions.

`BASE_PATH` contains persistent runtime state.

---

## Stack files

```text
stack7_-_xyops/
├── .env.example
├── .gitignore
├── 01-prepare.sh
├── README.md
├── docker-compose.yml
└── jobs/
    ├── hermes-memory-sync.sh
    └── hermes-sandbox-audit.sh
```

Operational files excluded from Git:

```text
.env
.lock
```

The xySat runtime identity also remains outside Git.

---

## Runtime directories

```text
/opt/docker/runtime/service_-_xyops/
├── data/
├── conf/
└── logs/

/opt/docker/runtime/service_-_xysat/
├── config/
│   └── config.json
├── logs/
└── ssh/
    ├── id_ed25519
    ├── known_hosts
    └── ssh_config
```

The exact runtime content may evolve, but credentials and generated identity material remain runtime-only.

---

## Security contract

Neither the conductor nor the worker receives unrestricted host control.

Stack7 must not receive:

```text
/var/run/docker.sock
privileged: true
host networking
the host root filesystem
unrestricted /opt/docker mounts
```

The conductor does not launch an embedded local xySat.

A dedicated external xySat worker is used instead.

The worker receives only the paths required by approved jobs.

---

## Conductor configuration

The conductor uses the Docker-internal satellite configuration:

```yaml
XYOPS_satellite__config__host: xyops
XYOPS_satellite__config__port: "5522"
XYOPS_satellite__config__secure: "false"
```

This is deliberately separate from the human-facing base application URL:

```text
https://xyops.casa.lan
```

---

## Prepare

Create the local operational environment:

```bash
cp .env.example .env
chmod 600 .env
```

Review `.env`, then run:

```bash
./01-prepare.sh
```

The preparation script:

- treats `.env` as read-only;
- validates required variables;
- validates pinned image versions;
- validates the external Docker network;
- validates Compose syntax;
- rejects Docker socket access;
- rejects privileged mode;
- rejects unrestricted `/opt/docker` mounts;
- rejects embedded conductor xySat configuration;
- creates persistent runtime directories;
- preserves an existing enrolled xySat configuration;
- does not create a fake `config.json`;
- creates `.lock` only after successful validation.

---

## Starting the conductor

```bash
docker compose up -d xyops
```

Validate:

```bash
docker compose ps xyops

docker exec xyops \
  curl -fsS http://127.0.0.1:5522/api/app/ping
```

Expected response:

```json
{"code":0}
```

---

## HAProxy integration

Browser-facing access is published through Stack1 HAProxy:

```text
https://xyops.casa.lan
```

HAProxy routes internally to:

```text
xyops:5522
```

The internal wildcard certificate covers:

```text
*.casa.lan
```

No direct host-port publication is required for xyOps.

---

## xySat enrollment

xySat enrollment is performed only after the conductor is operational.

The xyOps UI generates a temporary bootstrap token.

That token:

- is sensitive;
- is temporary;
- must not be committed;
- must not be stored in `.env`;
- must not be pasted into documentation.

The resulting permanent runtime configuration is stored at:

```text
/opt/docker/runtime/service_-_xysat/config/config.json
```

Inside the worker:

```text
/etc/xysat/config.json
```

Expected file permission:

```text
0600
```

The deployed worker configuration must use:

```text
host   = xyops
port   = 5522
secure = false
```

The bootstrap flow is one-time. Once `config.json` exists, normal worker startup uses the persisted enrolled identity.

---

## Starting the worker

xySat is behind the Compose `worker` profile.

```bash
docker compose --profile worker up -d xysat
```

Validate:

```bash
docker compose --profile worker ps
docker exec xysat getent hosts xyops
docker exec xysat curl -fsS http://xyops:5522/api/app/ping
```

The worker should then appear Online in the xyOps Servers UI.

---

## Worker filesystem access

xySat is not given general host filesystem access.

### Hermes Git-backed memory

Writable mount:

```text
/opt/docker/runtime/service_-_hermes-memory/data
    ->
/work/hermes-memory
```

This is the only Stack6 runtime state that the memory-sync job may modify.

### Hermes sandbox

Read-only mount:

```text
/opt/docker/runtime/service_-_hermes-sandbox/data/workspace
    ->
/work/hermes-sandbox
```

The worker must not receive:

```text
/opt/docker/runtime/service_-_hermes-sandbox/data/home
```

This protects sandbox home / authorization state.

### Scheduler scripts

Read-only mount:

```text
/opt/docker/stacks/stack7_-_xyops/jobs
    ->
/opt/xyops/jobs
```

xySat can execute scheduler scripts but cannot modify their source.

---

## Dedicated Gitea SSH identity

The Hermes memory job uses a dedicated SSH identity.

The worker does **not** mount:

```text
/root/.ssh
```

Instead, only scheduler-specific material is exposed read-only:

```text
/run/hermes-memory-ssh/
├── id_ed25519
├── known_hosts
└── ssh_config
```

The Git remote is:

```text
ssh://git@gitea/ea1het/hermes-memory.git
```

Logical hostname resolution:

```text
Host:
    gitea -> git.casa.lan:2222

xySat / redlocal:
    gitea -> Docker DNS -> gitea:2222
```

The Gitea ED25519 host key is pinned in `known_hosts`, and strict host-key checking is enabled.

---

## Worker process identity

The xySat container runs its agent as root.

An attempt to drop the Git job to UID `10000` using `setpriv` failed because the image does not contain a passwd entry for that UID.

The final design therefore keeps xySat root **inside the container** while constraining its host impact through explicit mounts.

The Hermes memory job restores ownership / permissions on exit:

```text
working tree: 10000:10000
MEMORY.md:    10000:10000 mode 0640
USER.md:      10000:10000 mode 0640
```

The security boundary is the allowed filesystem surface, not access to the host root or Docker daemon.

---

## Job: Hermes Memory Sync

Script:

```text
jobs/hermes-memory-sync.sh
```

Purpose:

```text
Hermes memory
    ->
Git working tree
    ->
Gitea hermes-memory/main
```

The job is intentionally conservative.

Supported automatic states:

```text
local == remote + no changes
    -> no-op

local == remote + MEMORY.md / USER.md changes
    -> commit + push

remote ahead + clean local tree
    -> fast-forward

local ahead
    -> push
```

The job refuses automatic resolution for:

```text
divergent Git history
remote ahead while unsaved local memory exists
changes outside MEMORY.md / USER.md
unexpected branch
unexpected origin
```

It never force-pushes.

An internal `flock` prevents overlapping executions.

### xyOps Event

```text
Title:
Hermes Memory Sync

Target:
scheduler-worker

Triggers:
Manual
Every 10 minutes

Maximum concurrent jobs:
1

Maximum runtime:
300 seconds
```

No catch-up schedule is required.

### Validated behavior

The job has been validated for:

```text
clean no-op
real modification
commit
push
content restoration
local/remote equality
automatic scheduled execution
```

---

## Job: Hermes Sandbox Audit

Script:

```text
jobs/hermes-sandbox-audit.sh
```

The policy is deliberately audit-only.

The job:

- verifies the workspace;
- reports filesystem capacity;
- reports workspace size;
- reports top-level objects;
- reports file-age statistics;
- enumerates symlinks;
- detects unexpected special files;
- recognises the persistent `venv`;
- reports unclassified top-level objects.

It does **not** delete anything.

The current sandbox workspace contains a persistent Python virtual environment:

```text
/workspace/venv
```

A generic age-only deletion rule would therefore be unsafe.

### xyOps Event

```text
Title:
Hermes Sandbox Audit

Target:
scheduler-worker

Triggers:
Manual
Daily at 03:30 Europe/Madrid

Maximum concurrent jobs:
1

Maximum runtime:
300 seconds
```

Automatic deletion will only be introduced after a specific class of transient artifact has a documented lifecycle.

---

## Runtime state that must never be committed

Never commit:

```text
.env
.lock
xySat config.json
xySat auth tokens
bootstrap tokens
SSH private keys
xyOps secret_key
xyOps database/runtime state
job runtime logs
```

The conductor's persisted configuration under:

```text
/opt/docker/runtime/service_-_xyops/conf
```

may contain security-sensitive state and is runtime-only.

---

## Validated paths

The following paths have been tested end-to-end:

```text
Browser
  -> HAProxy
  -> xyOps

xySat
  -> Docker DNS
  -> xyops:5522

xyOps
  -> scheduler-worker / xySat
  -> Shell Plugin
  -> hermes-memory-sync.sh
  -> Gitea

xyOps
  -> scheduler-worker / xySat
  -> Shell Plugin
  -> hermes-sandbox-audit.sh
```

The worker has also been validated to see the sandbox workspace as read-only.

---

## Design principle

Stack7 exists to add controlled automation without weakening the isolation model of the rest of the platform.

> **Scheduling a privileged operation does not require making the scheduler privileged.**

Access is granted per job, per filesystem path and only to the degree required.


