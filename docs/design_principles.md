<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Design principles

[Reading guide](../README.md#reading-guide) · Next: [Operations](operations.md)

The rules the code follows. Changes should keep them true.

## Operation

- **One stack, one owner.** A stack owns its Compose file, configuration, and runtime directories. Shared host resources (directories, network, CA, TLS) belong to Stack 00 alone.
- **Explicit over automatic.** Each command acts on one stack and does one thing. Nothing starts dependencies, waits for readiness, or runs optional setup implicitly; those remain separate scripts.
- **Prepared is not running.** `.lock` records a successful preparation. Liveness comes from `status`, never from the lock or from a successful `start`.
- **Persistent state is never regenerated.** Preparation preserves PostgreSQL data, secrets, keys, and user-edited settings. A retry must be safe.
- **Fail closed.** Unexpected state (symlinks where files belong, unknown schemas, mismatched secrets) stops the command with an explanation instead of being "repaired".

## Security

- **Configured secrets live in one place.** The root `.env` (`root:root 0600`) holds every configured secret, and each stack links to it. Runtime-generated material (SSH keys, runner token) stays in the stack's runtime directory. Secrets are never printed and never written to Git-tracked files. A private backup is made before any change.
- **Least privilege across boundaries.** AI consumers use scoped LiteLLM keys, never the master key or provider credentials. Hermes gets an SSH sandbox, not the Docker socket.
- **No silent fallback.** A missing optional provider (for example local web search) leaves its feature disabled; it never switches to an undeclared external service.

## Code

- **Standard library only.** Wrappers and scripts need only Python 3 and Docker Compose.
- **No bytecode in the checkout.** Every entry point sets `sys.dont_write_bytecode` and children run with `-B`.
- **Pass-through CLI.** `./local-ai` forwards arguments and exit codes unchanged; every command has `--help`.
- **Tests check contracts.** Tests mock Docker and the host, and exist where they catch a real bug or pin a real contract.
- **MPL-2.0 headers** on every file, enforced in CI ([exceptions](license-header-exceptions.md)).
