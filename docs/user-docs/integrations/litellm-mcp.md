<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# LiteLLM MCP gateway

Stack3 is the shared MCP gateway for local AI clients. The project keeps only infrastructure-level MCP behavior in Git; MCP servers, virtual keys, access groups and per-client permissions are deliberately managed dynamically through LiteLLM and persisted in its PostgreSQL state.

This separation prevents the protected root `.env` and tracked `config.yaml` from becoming a static catalog of consumers.

## Gateway endpoint

Clients on the internal Docker network use the aggregate LiteLLM MCP endpoint:

```text
http://litellm:4000/mcp
```

Port 4000 is not a supported direct host exposure. External consumers require an explicitly designed HTTPS ingress path before they are considered supported.

## Dynamic objects

The following belong to LiteLLM-managed state rather than tracked configuration:

- MCP server registrations
- virtual keys for MCP clients
- MCP access groups
- per-key and per-team MCP permissions
- allowed tools
- future client identities

Each consumer receives its own credential. In particular, the inference credential and MCP credential are separate security principals.

For Hermes the client-owned credential is represented by:

```text
LITELLM_MCP_API_KEY
```

and is consumed by Stack6, not stored in Stack3's tracked configuration.

## Validated integration pattern

The validated pattern is:

```text
AI client --> LiteLLM MCP gateway --> upstream MCP server
```

A validated read-only example uses a public MCP service as the upstream. The upstream service is an integration example, not a hard-coded platform dependency. Additional MCP servers can be registered without changing the Stack3 source contract provided their trust and permissions are reviewed.

## Validation sequence

A new upstream/client relationship should be introduced in this order:

1. Prove LiteLLM itself is healthy.
2. Register the upstream MCP server through the supported LiteLLM administration plane.
3. Confirm upstream reachability and tool discovery from LiteLLM.
4. Create a dedicated virtual key for the consuming client.
5. Grant only the required MCP access and tools.
6. Configure that credential in the owning client stack.
7. Reload/reconnect the client if required.
8. Execute a real end-to-end tool call and verify the path is client -> LiteLLM -> upstream.

Do not treat successful tool discovery alone as an end-to-end qualification.

## Security boundary

LiteLLM is the MCP admission and routing boundary. Clients should not need credentials for every upstream integration and should not connect directly to arbitrary upstream MCP services when the gateway path is intended.

For Hermes, the MCP server is treated as untrusted: the intended contract is tool consumption, not broad prompt/resource authority. Credential scope should therefore remain least-privilege and separate from model-inference credentials.

## Persistence and recovery

MCP registrations and access policy are part of LiteLLM's managed PostgreSQL state. Stack3 recovery therefore depends on the existing logical PostgreSQL backup/restore contract rather than on copying tracked YAML or ad-hoc MCP configuration files.

Operational version management for LiteLLM remains independent from this integration design. LiteLLM is currently non-selectable in the guarded upgrade executor until its compatibility and migration contract is explicitly qualified.
