# Stack6 Phase 1 — Telegram, LiteLLM MCP Gateway and Git-backed memory

This phase extends the existing Hermes deployment without changing its core boundaries:

- model inference still goes only through LiteLLM
- arbitrary command execution still goes only through the isolated SSH sandbox
- SearXNG and Firecrawl remain the web backends
- Buzz remains configured as before
- Telegram is added as an outbound-polling messaging channel
- LiteLLM becomes the single MCP gateway
- Hermes memory moves to a separate Git working tree

Calendly, A2A, email, additional plugins and automatic sandbox cleanup are intentionally out of scope.

## Versions

The deployment is pinned to the currently validated Hermes release:

```text
HERMES_IMAGE=nousresearch/hermes-agent
HERMES_VERSION=v2026.8.31
```

The corresponding running Hermes version is:

```text
Hermes Agent v0.21.0 (2026.8.31)
```

Stack3 pins LiteLLM independently.

## New `.env` values

Add the values introduced in `.env.template` to the operational `.env` before running Compose validation.

### Hermes image

```text
HERMES_VERSION=v2026.8.31
```

### MCP client

```text
LITELLM_MCP_URL=http://litellm:4000/mcp
LITELLM_MCP_API_KEY=<virtual key created manually in LiteLLM Admin UI>
```

Do not copy this key into Stack3. It is the credential of the Hermes MCP client.

### Telegram

```text
TELEGRAM_BOT_TOKEN=<BotFather token for ea1het_nhi_bot>
```

Do not add a Telegram webhook URL. Hermes will use long polling and therefore requires no public inbound route.

The token itself enables Telegram in Hermes v0.21.0. Authorization remains deny-by-default until a user is paired or allowlisted.

### Git memory

```text
HERMES_MEMORY_SERVICE=service_-_hermes-memory
GITMEM_REPOSITORY=<private Gitea repository URL>
GITMEM_BRANCH=main
```

Git credentials are deliberately external to `.env`.

## Memory layout

Host:

```text
/opt/docker/service_-_hermes/data
/opt/docker/service_-_hermes-memory/data
```

The memory service contains the real Git working tree:

```text
service_-_hermes-memory/
└── data/
    ├── .git/
    ├── MEMORY.md
    └── USER.md
```

Compose mounts it as:

```text
service_-_hermes-memory/data -> /opt/data/memories
```

The active `MEMORY.md` and `USER.md` seen by Hermes are therefore the Git working tree files themselves, not copies.

## Preparing the memory repository

Create a private Gitea repository with branch `main` and both files already present:

```text
MEMORY.md
USER.md
```

The files may be empty, but they must exist in the repository.

Then stop Hermes and run:

```bash
cd /opt/docker/stack6_-_hermes
sudo bash ./04-gitmem.sh
```

`04-gitmem.sh`:

- clones the configured branch if the working tree does not exist
- validates `origin`
- validates the active branch
- requires `MEMORY.md` and `USER.md`
- validates permissions for the Hermes UID/GID
- refuses to overwrite a non-Git directory
- checks existing legacy Hermes memory before the new mount masks it
- never pulls, merges, rebases, commits, pushes or resets

If an existing file below:

```text
service_-_hermes/data/memories/
```

differs from the Git version, the script stops. Migrate that memory into the private repository deliberately before continuing.

Periodic Git synchronization is intentionally deferred to the future scheduler stack.

## LiteLLM MCP Gateway

Hermes has one MCP definition only:

```text
litellm_gateway -> http://litellm:4000/mcp
```

Individual servers such as trivago are not declared in Hermes.

The responsibility split is:

```text
Hermes -> LiteLLM MCP Gateway -> trivago / future MCP servers
```

Hermes marks the gateway as `untrusted`. Write-capable MCP tools therefore remain subject to Hermes approval behavior unless their MCP metadata identifies them as read-only.

Resources and prompts from the gateway are disabled in Phase 1; Hermes consumes MCP tools only.

## Telegram pairing

After Hermes starts, send a DM to `ea1het_nhi_bot`.

An unknown user should receive a pairing code. Approve it inside the container:

```bash
docker exec hermes hermes pairing approve telegram <PAIRING_CODE>
```

Useful commands:

```bash
docker exec hermes hermes pairing list
docker exec hermes hermes pairing revoke telegram <NUMERIC_USER_ID>
```

No `TELEGRAM_ALLOWED_USERS` value is required for the initial pairing workflow.

## Deployment order

Recommended Phase 1 order:

1. Update Stack3 `.env` with the pinned LiteLLM image/version.
2. Reprepare/recreate LiteLLM using the normal Stack3 lifecycle.
3. In the LiteLLM Admin UI, add the official trivago MCP server.
4. Validate LiteLLM can discover trivago tools.
5. In LiteLLM, create a dedicated virtual key for the Hermes MCP client and grant only the intended MCP access.
6. Add the new Stack6 `.env` values, including Telegram token and the Hermes MCP virtual key.
7. Create/seed the private Gitea memory repository.
8. Stop Stack6, remove `.lock` deliberately and run `01-prepare.sh` using the normal lifecycle.
9. Run `sudo bash ./04-gitmem.sh`.
10. Start/recreate Stack6.
11. Pair the Telegram user.
12. Validate Hermes MCP discovery; use `/reload-mcp` if required.
13. Ask Hermes a trivago-backed hotel-search question and verify the end-to-end path.

## Phase 1 validation targets

A successful deployment should prove all of the following independently:

```text
Hermes -> LiteLLM -> local model
Hermes -> SSH -> isolated sandbox
Hermes -> SearXNG / Firecrawl
Hermes -> Buzz
Telegram -> Hermes
Hermes -> LiteLLM MCP Gateway -> trivago
Hermes -> /opt/data/memories -> Git working tree
```

Only after these paths are stable should Calendly or scheduled maintenance be added.
