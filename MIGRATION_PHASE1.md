# Phase 1 migration runbook

This runbook migrates the current local hybrid AI deployment to the Phase 1 design:

- pin LiteLLM to `1.99.1`
- use LiteLLM as the shared MCP Gateway
- add the official trivago MCP as the first upstream MCP server
- pin Hermes to `v2026.8.31` / Hermes Agent `v0.21.0`
- add Telegram using outbound long polling
- move Hermes `MEMORY.md` and `USER.md` to a separate Git-backed working tree

The following remain out of scope:

- Calendly
- email
- A2A
- additional Hermes plugins
- scheduler container
- periodic Git sync
- automatic sandbox cleanup

The migration is intentionally split into checkpoints so each layer can be validated before moving to the next.

---

## 0. Preconditions

Expected current deployment paths:

```text
/opt/docker/stack3_-_litellm
/opt/docker/service_-_litellm
/opt/docker/stack6_-_hermes
/opt/docker/service_-_hermes
/opt/docker/service_-_hermes-sandbox
```

Expected target memory path:

```text
/opt/docker/service_-_hermes-memory/data
```

Expected pinned versions:

```text
LiteLLM: 1.99.1
Hermes image tag: v2026.8.31
Hermes runtime: v0.21.0 (2026.8.31)
```

Before changing anything, record the currently running containers and images:

```bash
docker compose -f /opt/docker/stack3_-_litellm/docker-compose.yml ps
docker compose -f /opt/docker/stack6_-_hermes/docker-compose.yml ps

docker inspect litellm --format '{{.Config.Image}} {{.Image}}'
docker inspect hermes --format '{{.Config.Image}} {{.Image}}'
```

Do not delete the existing Docker images during this migration. They are the local rollback point until Phase 1 is validated.

---

# Checkpoint A — Stack3 / LiteLLM version pinning

## A1. Update the operational Stack3 `.env`

Preserve every existing secret and add only the image variables:

```dotenv
LITELLM_IMAGE=ghcr.io/berriai/litellm-database
LITELLM_VERSION=1.99.1
```

Do not replace or regenerate:

```text
LITELLM_MASTER_KEY
LITELLM_SALT_KEY
LITELLM_DB_PASSWORD
UI_PASSWORD
```

`LITELLM_SALT_KEY` is especially important because LiteLLM uses it for encrypted data persisted in PostgreSQL.

## A2. Validate the desired Compose image

From Stack3:

```bash
cd /opt/docker/stack3_-_litellm
docker compose config | grep -A2 'image:'
```

The resolved LiteLLM image must be:

```text
ghcr.io/berriai/litellm-database:1.99.1
```

and must not contain `latest`.

## A3. Reprepare Stack3

Stop only LiteLLM before deliberately removing its stack lock:

```bash
cd /opt/docker/stack3_-_litellm
docker compose stop litellm
rm -f .lock
sudo ./01-prepare.sh
sudo ./02-postgres.sh
```

`02-postgres.sh` must preserve the existing LiteLLM database and only reconcile its PostgreSQL identity/provisioning.

## A4. Recreate LiteLLM

```bash
docker compose up -d --force-recreate litellm
docker compose ps
docker compose logs --tail=100 litellm
```

Validate the runtime version/image:

```bash
docker inspect litellm --format '{{.Config.Image}}'
```

Expected:

```text
ghcr.io/berriai/litellm-database:1.99.1
```

Validate liveness from inside the shared network or with the existing HAProxy route as appropriate.

### STOP POINT A

Do not continue until existing model inference still works through LiteLLM.

At minimum verify an existing local model/alias that Hermes already uses.

If LiteLLM fails, stop here and restore the previously recorded image/configuration before touching Stack6.

---

# Checkpoint B — LiteLLM MCP Gateway + trivago

MCP servers and client permissions are dynamic state. They are created in the LiteLLM Admin UI and stored in PostgreSQL, not committed to Stack3 configuration.

## B1. Add trivago in LiteLLM

Open the LiteLLM Admin UI and navigate to:

```text
MCP Tools -> New MCP Server
```

Use:

```text
Name / alias: trivago
URL: https://mcp.trivago.com/mcp
Transport: HTTP / Streamable HTTP
Authentication: none
```

Do not add an API key for trivago.

If the UI offers a connection/tool preview, use it before saving or immediately after saving.

Expected upstream tools include:

```text
trivago-accommodation-search
trivago-accommodation-radius-search
trivago-destination-price-trends
```

## B2. Validate LiteLLM -> trivago before involving Hermes

Use LiteLLM's MCP UI/tool preview to confirm that the server is reachable and its tools are discovered.

The first successful path must be:

```text
LiteLLM -> trivago MCP
```

not yet:

```text
Hermes -> LiteLLM -> trivago
```

## B3. Create the Hermes MCP client key

Create a dedicated LiteLLM virtual key for Hermes, for example:

```text
hermes-mcp
```

Grant that key access to the `trivago` MCP server and only the intended MCP tools/access group.

Do not reuse:

```text
LITELLM_MASTER_KEY
```

and do not put this client key in Stack3 `.env` or `config.yaml`.

Copy the generated key once for use later in Stack6 as:

```text
LITELLM_MCP_API_KEY
```

Future clients such as Cline and Continue.dev should receive separate virtual keys rather than sharing the Hermes key.

### STOP POINT B

Do not continue until:

```text
LiteLLM -> trivago
```

works independently.

---

# Checkpoint C — Private Gitea memory repository

## C1. Create the repository

Create a private Gitea repository dedicated to Hermes memory. Suggested name:

```text
hermes-memory
```

Use branch:

```text
main
```

The repository must contain these two normal files at its root:

```text
MEMORY.md
USER.md
```

Do not store unrelated agent state in this repository.

## C2. Inspect the existing Hermes memory before migration

On the Docker host:

```bash
sudo find /opt/docker/service_-_hermes/data/memories \
  -maxdepth 1 -type f -printf '%f %s bytes\n' 2>/dev/null || true
```

Inspect, if present:

```bash
sudo cat /opt/docker/service_-_hermes/data/memories/MEMORY.md 2>/dev/null || true
sudo cat /opt/docker/service_-_hermes/data/memories/USER.md 2>/dev/null || true
```

If either contains useful existing memory, put that exact valid Hermes memory content into the corresponding file in the private Gitea repository before running `04-gitmem.sh`.

Do not rely on the new bind mount to migrate old data automatically.

## C3. Decide repository access

`04-gitmem.sh` deliberately contains no credentials.

Configure Git/SSH credentials on the Docker host independently of Stack6, and verify that root can clone/read the repository because `04-gitmem.sh` currently runs as root.

For an SSH repository, test the relevant Gitea SSH connectivity before proceeding.

For HTTPS, do not embed username/password/token in `GITMEM_REPOSITORY`.

### STOP POINT C

The private repository must now be independently cloneable from the host and contain `MEMORY.md` and `USER.md`.

---

# Checkpoint D — Stack6 `.env`

Edit the existing operational:

```text
/opt/docker/stack6_-_hermes/.env
```

Preserve all existing secrets and add/update the Phase 1 values.

## D1. Hermes image pin

```dotenv
HERMES_IMAGE=nousresearch/hermes-agent
HERMES_VERSION=v2026.8.31
```

## D2. External memory service

```dotenv
HERMES_MEMORY_SERVICE=service_-_hermes-memory
```

## D3. LiteLLM MCP Gateway

```dotenv
LITELLM_MCP_URL=http://litellm:4000/mcp
LITELLM_MCP_API_KEY=<the dedicated hermes-mcp virtual key created in LiteLLM>
```

This MCP key is independent from the existing model-inference key:

```text
LITELLM_API_KEY      -> Hermes -> LiteLLM model inference
LITELLM_MCP_API_KEY  -> Hermes -> LiteLLM MCP Gateway
```

## D4. Telegram

```dotenv
TELEGRAM_BOT_TOKEN=<BotFather token for ea1het_nhi_bot>
```

Do not define a Telegram webhook URL. Phase 1 uses outbound long polling.

Do not put the bot token in Git.

## D5. Git memory

```dotenv
GITMEM_REPOSITORY=<private Gitea repository URL>
GITMEM_BRANCH=main
```

No Git password/token belongs in this `.env`.

---

# Checkpoint E — Reprepare Stack6 without starting it

## E1. Stop Stack6

```bash
cd /opt/docker/stack6_-_hermes
docker compose stop
```

Confirm both containers are stopped:

```bash
docker inspect hermes --format '{{.State.Running}}' 2>/dev/null || true
docker inspect hermes-sandbox --format '{{.State.Running}}' 2>/dev/null || true
```

Both existing containers, when present, should report:

```text
false
```

## E2. Remove the prepare lock deliberately

```bash
rm -f .lock
```

Do not run `02-cleanup.sh` unless `01-prepare.sh` explicitly reports shadow runtime configuration that requires cleanup.

## E3. Run prepare

```bash
sudo ./01-prepare.sh
```

This validates the runtime contract, including:

```text
HERMES_VERSION
HERMES_MEMORY_SERVICE
LITELLM_MCP_URL
LITELLM_MCP_API_KEY
TELEGRAM_BOT_TOKEN
```

It does not create or modify the memory Git working tree.

### STOP POINT E

Do not run `docker compose up` yet.

---

# Checkpoint F — Prepare the Git-backed memory worktree

Run:

```bash
cd /opt/docker/stack6_-_hermes
sudo bash ./04-gitmem.sh
```

Expected target:

```text
/opt/docker/service_-_hermes-memory/data
```

Expected structure:

```text
service_-_hermes-memory/
└── data/
    ├── .git/
    ├── MEMORY.md
    └── USER.md
```

`04-gitmem.sh` must not perform:

```text
pull
merge
rebase
commit
push
reset
```

Verify manually:

```bash
sudo git -c safe.directory=/opt/docker/service_-_hermes-memory/data \
  -C /opt/docker/service_-_hermes-memory/data status

sudo git -c safe.directory=/opt/docker/service_-_hermes-memory/data \
  -C /opt/docker/service_-_hermes-memory/data remote -v
```

The Compose memory bind uses `create_host_path: false`; if this worktree does not exist, Docker must fail rather than silently creating an empty memory directory.

### STOP POINT F

Do not start Hermes unless the worktree and both memory files are correct.

---

# Checkpoint G — Start/recreate Stack6

Validate Compose first:

```bash
cd /opt/docker/stack6_-_hermes
docker compose config --quiet
```

Then recreate:

```bash
docker compose up -d --build --force-recreate
docker compose ps
```

Inspect logs:

```bash
docker compose logs --tail=150 hermes
docker compose logs --tail=100 hermes-sandbox
```

Validate the pinned Hermes image/runtime:

```bash
docker inspect hermes --format '{{.Config.Image}}'
docker exec hermes hermes --version
```

Expected:

```text
nousresearch/hermes-agent:v2026.8.31
Hermes Agent v0.21.0 (2026.8.31)
```

Validate the memory mount:

```bash
docker exec hermes sh -lc 'ls -la /opt/data/memories && test -f /opt/data/memories/MEMORY.md && test -f /opt/data/memories/USER.md'
```

Validate the existing paths before testing the new features:

```text
Hermes -> LiteLLM -> existing local model
Hermes -> SSH -> hermes-sandbox
Hermes -> SearXNG / Firecrawl
Hermes -> Buzz
```

If an existing path regresses, stop here before pairing Telegram or debugging Trivago.

---

# Checkpoint H — Telegram pairing

Send a direct message from the intended Telegram account to:

```text
@ea1het_nhi_bot
```

The bot should return a one-time pairing code for an unknown user.

Approve it:

```bash
docker exec hermes hermes pairing approve telegram <PAIRING_CODE>
```

Inspect pairing state:

```bash
docker exec hermes hermes pairing list
```

Then send a normal private message to the bot and verify a normal Hermes response.

Phase 1 intentionally uses:

```text
private DM
long polling
no public webhook
no group configuration
```

---

# Checkpoint I — Hermes -> LiteLLM MCP -> trivago

Hermes contains one MCP server definition:

```text
litellm_gateway -> http://litellm:4000/mcp
```

Reload MCP discovery if necessary:

```text
/reload-mcp
```

from a Hermes conversation.

Then ask a request that clearly requires trivago, for example a hotel/accommodation search with a destination and dates/preferences.

The expected execution path is:

```text
Hermes
  -> LiteLLM MCP Gateway
      -> trivago MCP
          -> result
      <-
  <-
```

Hermes must not contain a direct trivago MCP URL or credential.

Verify the LiteLLM side independently through its MCP logs/UI if the tool is not discovered or invoked.

---

# Checkpoint J — Memory write validation

After Hermes is running, cause a small, non-sensitive memory update or use the Hermes memory tooling deliberately.

Then verify that the actual changed file is the Git working tree file:

```bash
sudo git -c safe.directory=/opt/docker/service_-_hermes-memory/data \
  -C /opt/docker/service_-_hermes-memory/data status --short
```

A Hermes memory change should appear as a modification of:

```text
MEMORY.md
```

or:

```text
USER.md
```

No automatic commit or push is expected in Phase 1.

---

# Final Phase 1 acceptance criteria

Phase 1 is accepted only when all of these paths work:

```text
Hermes -> LiteLLM -> local model
Hermes -> SSH -> isolated sandbox
Hermes -> SearXNG / Firecrawl
Hermes -> Buzz
Telegram DM -> Hermes
Hermes -> LiteLLM MCP Gateway -> trivago
Hermes -> /opt/data/memories -> service_-_hermes-memory/data Git worktree
```

and these remain absent:

```text
no Hermes Docker socket
no sandbox Docker socket
no Telegram webhook/public ingress
no direct Hermes -> trivago configuration
no Calendly
no email
no A2A
no automatic Git synchronization
no automatic sandbox cleanup
```

---

# Rollback strategy

Rollback should be done at the checkpoint that failed rather than resetting unrelated stacks.

## LiteLLM rollback

If failure occurs at Checkpoint A/B:

- stop LiteLLM
- restore the previous Stack3 `.env` image selection/configuration
- recreate the previously recorded image
- leave PostgreSQL data intact

Do not delete MCP database rows merely to roll back the container image unless a schema incompatibility has first been established.

## Hermes rollback

If failure occurs after Stack6 changes:

- stop Stack6
- restore the previous Stack6 source/configuration and `.env`
- recreate the previously recorded Hermes image
- remove only the new memory bind from the old Compose definition

The original memory below:

```text
/opt/docker/service_-_hermes/data/memories
```

is deliberately not deleted by this migration.

The Git-backed repository at:

```text
/opt/docker/service_-_hermes-memory/data
```

is also a separate lifecycle and must not be deleted as part of a Hermes runtime rollback.

Never use `git reset --hard`, force push, or an automatic merge as a rollback mechanism for agent memory.
