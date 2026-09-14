<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# ADR-0002: `local-ai` is the sole supported management interface

Status: Accepted

## Context

The project contains Python modules, shell scripts, Compose files and DR tools. Direct external coupling to any of those implementation details would make integrations fragile and would prevent internal refactoring.

## Decision

`./local-ai` is the only supported management interface for operators and external consumers. It is the project's anticorruption boundary.

Human consumers use normal CLI output. Machine consumers use the same commands with `--json` where the command exposes a stable machine contract. JSON contracts carry an independent `schema_version` and structured error codes.

Private management implementation lives under `commands/`; stack-owned lifecycle scripts remain in stack directories. Those implementation paths may be invoked internally and by tests, but external automation must not depend on their paths, language, filenames or argument contracts. The internal package organization is defined more specifically by ADR-0005.

## Consequences

- Documentation must show `./local-ai`, not direct Python or shell entry points, for supported operator workflows.
- An API, another CLI, MCP server, CI job or UI should wrap `local-ai --json` rather than import private Python modules.
- Private implementations may change without constituting a public API break as long as the `local-ai` contract remains compatible.
- Contract tests exercise `local-ai`; lower-level tests may still exercise private modules.
