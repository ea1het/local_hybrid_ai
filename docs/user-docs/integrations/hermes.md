<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Hermes integrations

Stack6 extends Hermes with local inference through LiteLLM, isolated command execution, optional web capabilities, messaging channels, MCP access and Git-backed portable memory. These integrations preserve the Stack6 security boundary: Hermes itself has no Docker socket and arbitrary command execution is delegated to the isolated SSH sandbox.

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

Do not copy a hard-coded Hermes version from documentation into an installation. Installation-owned version intent is authoritative after adoption; runtime observation and remote availability are separate facts.

```bash
./local-ai status
./local-ai upgrade
```

`status` answers whether Stack6 is operational/coherent. `upgrade` is the normal human version view and reports installed, available, selectable and selected state. `upgrade check` remains only a compatibility alias.

The guarded executor has been qualified on a real Hermes upgrade through `v2026.9.11`; that is qualification evidence for the mechanism, not a desired-version declaration and not a claim about the latest upstream release.

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

Telegram uses outbound long polling, so no inbound webhook route is required. The bot token belongs to protected installation configuration. Authorization remains deny-by-default until a user is paired or explicitly allowed. Pairing is a Hermes application operation, not a `local-ai` platform-management command.

## Git-backed memory

Portable user memory is intentionally separate from disposable Hermes runtime state. The durable contract is the configured Git repository and branch containing regular `MEMORY.md` and `USER.md` files. Git credentials remain external operator prerequisites rather than values committed to Git. The runtime working tree lives under the installation runtime area and is mounted into Hermes at `/opt/data/memories`.

Only Git-backed memory content is considered durable Stack6 user state for recovery. Hermes sessions, local state databases, caches, packages, logs, `SOUL.md` and sandbox contents are reconstructable/disposable.

The memory-sync sidecar records installation intent separately from the Git provider. Its SSH bootstrap material is external operator-owned state and is intentionally required again during clean disaster recovery. Preparation/adoption validates repository origin, branch, required files, permissions and collision with legacy local memory; it must not silently overwrite an unrelated directory or rewrite repository history.

## Optional Stack2 web capabilities

Stack6 can consume `web.search` and `web.extract` when Stack2 is prepared and READY. These are capability relationships, not hard dependencies. Reconciliation enables them only after the provider is proven ready and disables/withholds them when the provider is absent.

## Validation targets

A fully integrated installation should prove each configured path independently: Hermes -> LiteLLM -> model; Hermes -> SSH -> sandbox; optional Hermes -> Stack2 web tools; optional messaging; Hermes -> LiteLLM MCP -> MCP server; and Hermes -> `/opt/data/memories` -> Git working tree. Failure of an optional integration must not invalidate the isolation or persistence contracts of the others.

## Recovery implications

Stack6 runtime is reconstructable. Durable memory is externalized through Git, while memory-sync SSH bootstrap material remains an external operator prerequisite. Recovery validates Git repository/branch alignment and re-provisions that external SSH material rather than backing up disposable Hermes runtime directories.
