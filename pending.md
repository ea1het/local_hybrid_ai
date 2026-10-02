<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Pending work

[Reading guide](README.md#reading-guide)

Only open items. Finished work belongs in Git history.

## Operations

- **Memory-sync SSH bootstrap.** `prepare-maintenance-sidecars.py` expects `ssh_config`, `id_ed25519`, and `known_hosts` in `${MEMORY_SYNC_SERVICE}/ssh`, but nothing creates or documents them. Package that step.
- **Backup and restore.** No tooling exists. Data to protect: LiteLLM PostgreSQL, `service_-_gitea`, `service_-_open-webui/data`, Hermes memory repository, and the root `.env`.

## Code inconsistencies found during the documentation review (2026-10-02)

- **Open WebUI default model.** `DEFAULT_MODELS=basic_autorouter`, and `reconcile-model-policy.py` creates that entry with no base model, yet LiteLLM only publishes `mlx/local-{general,agent,coding}`. Confirm where `basic_autorouter` comes from.
- **`pyproject.toml`** declares the package `local_ai_cli` under `src/`, which does not exist.
