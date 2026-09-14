<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Hermes integrations

Stack6 extends Hermes with local inference through LiteLLM, isolated command execution, optional web capabilities, messaging channels, MCP access and Git-backed portable memory. These integrations must preserve the Stack6 security boundary: Hermes itself has no Docker socket and arbitrary command execution is delegated to the isolated SSH sandbox.

## Architecture boundaries

The supported integration model is:

- model inference -> LiteLLM
- arbitrary commands -> isolated SSH sandbox
- web search/extraction -> optional Stack2 capabilities
- Buzz -> optional messaging channel
- Telegram -> outbound long polling
- MCP -> LiteLLM as the single gateway
- durable user memory -> separate Git working tree mounted read/write into Hermes

An absent optional capability must fail closed or remain unavailable; it must not silently become a cloud fallback.

## Version state

Do not copy a hard-coded Hermes version from this document into an installation. The installation owns its selected/desired version and the public CLI reports runtime and upgrade state.

```bash
./local-ai status
./local-ai upgrade check
```

The guarded executor has been qualified on a real Hermes upgrade through `v2026.9.11`; that qualification is evidence for the upgrade mechanism, not a promise that this tag remains the latest or universally desired version.

## MCP client

Hermes connects to LiteLLM as one MCP gateway:

```text
LITELLM_MCP_URL=http://litellm:4000/mcp
LITELLM_MCP_API_KEY=<dedicated Hermes MCP virtual key>
```

The model-inference key and MCP key are deliberately separate:

```text
LITELLM_API_KEY      -> model inference
LITELLM_MCP_API_KEY  -> MCP gateway
```

Individual upstream MCP servers are registered and authorized in LiteLLM rather than declared independently inside Hermes. See [LiteLLM MCP gateway](litellm-mcp.md).

## Telegram

Telegram uses outbound long polling, so no inbound webhook route is required. The bot token belongs to the protected installation configuration:

```text
TELEGRAM_BOT_TOKEN=<BotFather token>
```

Authorization remains deny-by-default until a user is paired or explicitly allowed. Pairing operations are Hermes application operations, not `local-ai` platform-management commands.

## Git-backed memory

Portable user memory is intentionally separate from disposable Hermes runtime state. The durable contract is the configured Git repository and branch containing regular `MEMORY.md` and `USER.md` files.

Typical installation configuration includes:

```text
HERMES_MEMORY_SERVICE=service_-_hermes-memory
GITMEM_REPOSITORY=<private Git repository URL>
GITMEM_BRANCH=main
```

Git credentials remain external operator prerequisites rather than values committed to Git. The runtime working tree lives under the installation runtime area and is mounted into Hermes at `/opt/data/memories`.

Only the Git-backed memory content is considered durable Stack6 user state for recovery. Hermes sessions, local state databases, caches, packages, logs, `SOUL.md` and sandbox contents are reconstructable/disposable.

### Desired-state and synchronization

The memory-sync sidecar records installation intent separately from the Git provider. Its SSH bootstrap material is external operator-owned state and is intentionally required again during a clean disaster recovery.

The preparation/adoption logic validates repository origin, branch, required files, permissions and collision with legacy local memory. It must not silently overwrite an unrelated directory or rewrite repository history.

## Optional Stack2 web capabilities

Stack6 can consume `web.search` and `web.extract` when Stack2 is prepared and available. These are capability relationships, not a hard-coded deployment dependency. The installer/reconciler discovers optional capability changes from manifests and reconciles prepared consumers when necessary.

## Validation targets

A fully integrated installation should prove each path independently:

```text
Hermes -> LiteLLM -> model
Hermes -> SSH -> isolated sandbox
Hermes -> SearXNG / Firecrawl        (when Stack2 is enabled)
Hermes -> Buzz                       (when enabled)
Telegram -> Hermes                   (when enabled)
Hermes -> LiteLLM MCP -> MCP server  (when configured)
Hermes -> /opt/data/memories -> Git working tree
```

A failure in one optional integration should not invalidate the isolation or persistence contracts of the others.

## Recovery implications

Stack6 is reconstructable except for the externalized Git-backed memory and the external operator-owned SSH material needed by memory synchronization. Recovery validates Git repository/branch alignment and re-provisions the external SSH material rather than backing up disposable Hermes runtime directories.
