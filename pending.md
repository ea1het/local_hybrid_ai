<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Pending work

[Reading guide](README.md#reading-guide)

Only open items. Finished work belongs in Git history.

## Operations

- **Memory-sync SSH bootstrap.** `prepare-maintenance-sidecars.py` expects `ssh_config`, `id_ed25519`, and `known_hosts` in `${MEMORY_SYNC_SERVICE}/ssh`. The Stack 60 README says to place the key manually, but no secure bootstrap process creates and validates all three files. Package that step.
- **Backup and restore.** Individual reconfiguration steps make local backups, but no coordinated backup and restore tooling covers LiteLLM PostgreSQL, `service_-_gitea`, `service_-_open-webui/data`, the Hermes memory repository, and the root `.env`.
- **LiteLLM configuration snapshot.** Produce and validate a compatible PostgreSQL snapshot of the operator-approved models, provider credentials, virtual keys, and MCP grants. Define a safe restore process that preserves the original `LITELLM_SALT_KEY`, reconciles consumer keys in `.env`, and does not overwrite a populated installation without explicit approval. No snapshot is included yet.

## Packaging

- **`pyproject.toml`.** The project metadata is named `local_ai_cli`, but the build includes only `version.py`; the operational CLI remains a source-tree entry point. Decide whether to package the full CLI or document this as version metadata only.
