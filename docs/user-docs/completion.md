<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Shell completion

`local-ai` provides TAB completion adapters for Bash and Zsh. Candidate calculation is source-local and derives stack/component information from current manifests rather than a static component catalog.

## Automatic installation

```bash
./local-ai completion install
./local-ai completion status
```

The installer detects the login/operator shell from `$SHELL`, supports Bash and Zsh, chooses a conventional target and writes only the generated completion file. Re-running it is idempotent. Unsupported/unknown shells fail without guessing a configuration and the command does not rewrite `.bashrc`, `.zshrc` or other startup files.

Targets are:

| Shell | root | unprivileged |
|---|---|---|
| Bash | `/etc/bash_completion.d/local-ai` | `~/.local/share/bash-completion/completions/local-ai` |
| Zsh | `/usr/local/share/zsh/site-functions/_local-ai` | `~/.local/share/zsh/site-functions/_local-ai` |

Writing a target proves that the generated adapter is installed at that path; it does **not** prove that an arbitrary shell configuration loads that directory. Bash user completion depends on an active bash-completion setup. Zsh completion depends on the target directory being present in `fpath` and completion initialization being enabled. The installer intentionally does not mutate shell startup configuration to manufacture those prerequisites.

`completion status` checks that the expected target exists and exactly matches the currently generated adapter. It is a file-state check, not a proof that the current interactive shell has loaded the completion system.

## Generate or load manually

The generators remain supported and side-effect free:

```bash
./local-ai completion bash
./local-ai completion zsh
```

For the current Bash session:

```bash
source <(./local-ai completion bash)
```

For the current Zsh session:

```zsh
source <(./local-ai completion zsh)
```

The generated adapter delegates candidate calculation to the private `local-ai __complete` endpoint. That endpoint is an implementation detail, not an operator command.

## Safety contract

Candidate calculation may read stack manifests and Compose source needed to validate manifest-driven inventory. It does not inspect Docker runtime state, query image registries, write the runtime inventory snapshot, change `.env`, select upgrades or execute lifecycle operations.

`completion install` is the explicit write operation: it writes only the selected shell-completion file and creates its parent directory when required. It does not modify stack/runtime state or shell startup files.

## Known grammar gaps

The current completion engine is implemented and usable, but two candidate-grammar discrepancies are tracked in the active backlog rather than hidden by documentation: selective `start`/`stop` completion currently proposes stable `stackN` identities while the primary human lifecycle syntax uses numeric stack IDs, and upgrade-policy completion includes a `show` candidate although inspection is action-less in the public CLI. Until those are corrected, the [CLI reference](cli.md) is authoritative for command syntax.
