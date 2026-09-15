<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Shell completion

`local-ai` provides TAB completion for Bash and Zsh. Candidate calculation remains derived from the public CLI grammar and manifest-declared component inventory.

## Automatic persistent installation

The normal operator workflow is:

```bash
./local-ai completion install
```

The command detects Bash or Zsh from the operator environment, chooses a persistent completion target, creates its parent directory when necessary, and writes the generated adapter. Re-running the command is idempotent. Unsupported shells fail without installing a guessed configuration.

Root installations use the conventional system locations `/etc/bash_completion.d/local-ai` for Bash and `/usr/local/share/zsh/site-functions/_local-ai` for Zsh. Unprivileged installations use the corresponding completion directories below the operator's `~/.local/share` tree.

Inspect the persistent state with:

```bash
./local-ai completion status
```

A newly installed completion is expected to be available in new shell sessions. The installer deliberately does not rewrite `.bashrc`, `.zshrc`, or other operator startup files.

## Generate or load manually

The original generators remain supported and side-effect free:

```bash
./local-ai completion bash
./local-ai completion zsh
```

For the current Bash session only:

```bash
source <(./local-ai completion bash)
```

For the current Zsh session only:

```zsh
source <(./local-ai completion zsh)
```

The generated adapter delegates candidate calculation to the private `local-ai __complete` endpoint. That endpoint is an implementation detail rather than an operator command.

## Safety contract

Candidate calculation is read-only and source-local. It may read stack manifests and Compose source needed to validate the manifest-driven inventory. It does not inspect Docker runtime state, query image registries, write the runtime inventory snapshot, change `.env`, select upgrades, or execute lifecycle operations.

`completion install` is the explicit exception to the no-write property: it writes only the selected shell-completion file. It does not modify stack/runtime state or shell startup files.
