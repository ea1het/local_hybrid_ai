<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Integrations

[← User documentation](../README.md) · [Documentation map](../../TOC.md)

Integration documentation describes supported ways for platform consumers to use capabilities without bypassing the `./local-ai` management boundary or stack security boundaries.

## Documents

- [Hermes](hermes.md) — agent integration, LiteLLM access, optional web capabilities and durable Git-backed memory.
- [LiteLLM MCP](litellm-mcp.md) — MCP access through the AI gateway.

## Related architecture and security

- [Stack relationships](../../stacks/README.md)
- [SDR-0002 — agent runtime without Docker socket](../../devel-docs/sdr/0002-agent-runtime-without-docker-socket.md)
- [SDR-0003 — least-privilege AI gateway credentials](../../devel-docs/sdr/0003-least-privilege-ai-gateway-credentials.md)
- [SDR-0004 — internal-only service networking](../../devel-docs/sdr/0004-internal-only-service-networking.md)
