# Hermes integrations

This document covers the permanent integration model for Stack6: Telegram, LiteLLM MCP Gateway and Git-backed memory.

## Architecture boundaries

The integrations extend Hermes without changing the core security model:

- model inference goes through LiteLLM
- arbitrary command execution goes through the isolated SSH sandbox
- SearXNG and Firecrawl remain the web backends
- Buzz remains an optional messaging channel
- Telegram uses outbound long polling
- LiteLLM is the single MCP gateway
- Hermes memory is mounted from a separate Git working tree

Calendly, A2A, email, additional plugins and automatic sandbox cleanup are not required by this installation.

## Versions

The validated Hermes image is:

```dotenv
HERMES_IMAGE=nousresearch/hermes-agent
HERMES_VERSION=v2026.8.31
```

This corresponds to Hermes Agent v0.21.0 (2026.8.31).

LiteLLM is pinned independently in Stack3.

## MCP client

Hermes connects to one MCP server definition only:

```dotenv
LITELLM_MCP_URL=http://litellm:4000/mcp
LITELLM_MCP_API_KEY=<dedicated Hermes MCP virtual key>
```

The inference key and MCP key are separate credentials:

```text
LITELLM_API_KEY      -> model inference
LITELLM_MCP_API_KEY  -> MCP gateway
```

Individual MCP servers are registered dynamically in LiteLLM rather than declared in Hermes.

The intended path is:

```text
Hermes -> LiteLLM MCP Gateway -> Trivago / future MCP servers
```

The gateway is configured as untrusted from Hermes. Resources and prompts are disabled; Hermes consumes MCP tools only.

A validated example is the Trivago MCP server, exposed through LiteLLM with three read-only tools.

## Telegram

Configure:

```dotenv
TELEGRAM_BOT_TOKEN=<BotFather token>
```

No webhook URL is required. Hermes uses outbound long polling.

Authorization remains deny-by-default until the user is paired or explicitly allowlisted.

Useful pairing commands:

```bash
docker exec hermes hermes pairing approve telegram <PAIRING_CODE>
docker exec hermes hermes pairing list
docker exec hermes hermes pairing revoke telegram <NUMERIC_USER_ID>
```

## Git-backed memory

Configure:

```dotenv
HERMES_MEMORY_SERVICE=service_-_hermes-memory
GITMEM_REPOSITORY=<private Git repository URL>
GITMEM_BRANCH=main
```

Git credentials are external to `.env`.

The host layout is:

```text
/opt/docker/runtime/service_-_hermes/data
/opt/docker/runtime/service_-_hermes-memory/data
```

The memory working tree is:

```text
service_-_hermes-memory/
└── data/
    ├── .git/
    ├── MEMORY.md
    └── USER.md
```

Compose mounts it as:

```text
/opt/docker/runtime/service_-_hermes-memory/data -> /opt/data/memories
```

The configured private repository must already contain regular `MEMORY.md` and `USER.md` files.

Prepare the working tree only after Stack6 preparation succeeds:

```bash
cd /opt/docker/stacks/stack6_-_hermes
sudo ./01-prepare.sh
sudo ./04-gitmem.sh
```

`04-gitmem.sh`:

- clones the configured branch when needed
- validates `origin`
- validates the active branch
- requires `MEMORY.md` and `USER.md`
- validates permissions for the Hermes UID/GID
- refuses to overwrite an existing non-Git directory
- compares non-empty legacy Hermes memory before the bind mount masks it
- never pulls, merges, rebases, commits, pushes or resets

Periodic Git synchronization belongs to a separate scheduler or maintenance component.

## Recommended deployment sequence

1. Validate local inference through LiteLLM.
2. Register required MCP servers in LiteLLM.
3. Create a dedicated Hermes MCP virtual key with only the required MCP access.
4. Create and seed the private memory repository.
5. Configure the operational Stack6 `.env`.
6. Run `01-prepare.sh`.
7. Run `04-gitmem.sh`.
8. Start Stack6.
9. Pair Telegram.
10. Validate MCP discovery and a real end-to-end MCP call.

## Validation targets

A healthy installation should prove these paths independently:

```text
Hermes -> LiteLLM -> local model
Hermes -> SSH -> isolated sandbox
Hermes -> SearXNG / Firecrawl
Hermes -> Buzz
Telegram -> Hermes
Hermes -> LiteLLM MCP Gateway -> MCP server
Hermes -> /opt/data/memories -> Git working tree
```

Only add further integrations after these paths remain stable.
