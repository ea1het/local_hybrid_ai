# LiteLLM MCP Gateway

Stack3 acts as the shared MCP gateway for local AI clients such as Hermes Agent, Cline and Continue.dev.

The stack keeps only infrastructure-level MCP behavior in Git. The following objects are intentionally managed dynamically from the LiteLLM Admin UI and persisted in PostgreSQL:

- MCP servers
- virtual keys for MCP clients
- MCP access groups
- per-key / per-team MCP permissions
- allowed tools
- future client identities

This avoids turning `.env` or `config.yaml` into a static catalog of consumers.

## Gateway endpoint

Clients use the aggregate LiteLLM MCP endpoint:

```text
http://litellm:4000/mcp
```

Clients outside the Docker network should use the appropriate HTTPS route if/when one is explicitly published for MCP. Do not expose port 4000 directly.

## Phase 1: Trivago

The first upstream MCP server is the official trivago MCP server:

```text
https://mcp.trivago.com/mcp
```

It requires no API key.

Create the server from the LiteLLM Admin UI rather than `config.yaml` so the configuration remains in PostgreSQL and can be changed independently of the stack source.

Suggested logical name:

```text
trivago
```

After adding it, verify that LiteLLM can discover the trivago tools before connecting Hermes.

Expected tools currently include:

```text
trivago-accommodation-search
trivago-accommodation-radius-search
trivago-destination-price-trends
```

## Client keys

Create a separate LiteLLM virtual key for each MCP consumer. Examples:

```text
hermes-mcp
cline-mcp
continue-mcp
```

Do not place those client keys in Stack3 `.env` or `config.yaml`.

Each client stores only its own key in its own configuration. For Hermes, the key belongs in Stack6 `.env` as:

```text
LITELLM_MCP_API_KEY
```

This keeps client lifecycle and permissions dynamic while Stack3 remains declarative.

## Recommended validation order

1. Start LiteLLM and confirm `/health/liveliness`.
2. Add `trivago` in the Admin UI.
3. Confirm the upstream MCP server is reachable and tools are discovered.
4. Create the `hermes-mcp` virtual key and grant only the required MCP access.
5. Configure that key in Stack6 `.env`.
6. Start Hermes and use `/reload-mcp` if necessary.
7. Ask Hermes a hotel-search question and confirm the tool path is Hermes -> LiteLLM -> trivago.

## Security model

LiteLLM owns MCP admission and routing. Hermes sees LiteLLM as one MCP server, not each upstream integration directly.

This gives one policy boundary for multiple clients:

```text
Hermes -------\
Cline ---------+--> LiteLLM MCP Gateway --> trivago
Continue.dev --/
```

Future MCP servers such as Calendly should be added only after this first path is proven end-to-end.
