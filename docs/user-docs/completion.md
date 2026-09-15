<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Shell completion

`local-ai` provides native TAB completion for Bash and Zsh. Completion is derived from the public CLI grammar and the current manifest-declared component inventory; component names are not maintained in a second static list.

## Bash

Load completion for the current shell with:

```bash
source <(./local-ai completion bash)
```

For a persistent installation, write the generated output to the completion directory used by the operating system or shell configuration.

## Zsh

Load completion for the current shell with:

```zsh
source <(./local-ai completion zsh)
```

The generated adapter delegates candidate calculation to the private `local-ai __complete` endpoint. That endpoint is an implementation detail rather than an operator command.

## Safety contract

TAB completion is read-only and source-local. It may read stack manifests and Compose source needed to validate the manifest-driven inventory. It does not inspect Docker runtime state, query image registries, write the runtime inventory snapshot, change `.env`, select upgrades, or execute lifecycle operations.

Consequently completion remains fast and deterministic even when the deployment has no registry/network access. If source inventory is temporarily invalid, interactive completion fails quietly instead of interrupting the shell; `./local-ai doctor` or `./local-ai inventory rescan` should be used to diagnose the underlying source inconsistency.
