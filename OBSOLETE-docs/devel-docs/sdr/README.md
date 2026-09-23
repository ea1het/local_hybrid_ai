<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Security Decision Records

[Documentation TOC](../../TOC.md) · [Developer documentation](../README.md) · [Architecture decisions](../adr/README.md) · [OpenSpec](../openspec/README.md)

SDRs capture security decisions whose rationale is not obvious from Compose, shell scripts or manifests. An SDR answers: **what threat or risk exists, what security decision was made, what residual risk remains, and how is it verified?** Architectural shape belongs in an ADR; a decision can reference both an ADR and an SDR when architecture and security overlap.

Status values: `proposed`, `accepted`, `superseded`, `retired`.

| SDR | Status | Security decision |
|---|---|---|
| [0001](0001-protected-operational-config-in-backups.md) | accepted | Carry protected operational configuration in complete recovery points with restrictive local controls |
| [0002](0002-agent-runtime-without-docker-socket.md) | accepted | Keep Hermes isolated from the Docker socket |
| [0003](0003-least-privilege-ai-gateway-credentials.md) | accepted | Use dedicated least-privilege LiteLLM application credentials |
| [0004](0004-internal-only-service-networking.md) | accepted | Keep internal services on `redlocal` without default host publication |
| [0005](0005-open-webui-explicit-model-access.md) | accepted | Preserve explicit Open WebUI model authorization rather than bypassing access control |

The current stack relationships that realize these decisions are summarized in the [stack map](../../stacks/README.md). Behavioural consequences and executable evidence are linked from [OpenSpec traceability](../openspec/traceability.md).
