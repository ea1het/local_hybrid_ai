<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Current implementation state

This page describes the implementation that exists in the current source tree. It is not a roadmap or chronology. Superseded designs are mentioned only where necessary to prevent use of a retired interface.

## Stack and component model

The platform contains eight independently owned stacks, 0 through 7. Stack0 is the common foundation. Stack6 and Stack7 require Stack3. Stack2 capabilities are optional to AI consumers.

## Source, runtime and version authority

Git contains the bootstrap/source baseline. Mutable installation state is installation-owned and outside the source checkout.

## Lifecycle

The lifecycle is `PREPARE → DEPLOY → READY → RECONCILE → VERIFY`. A stack `.lock` means PREPARED only. Selective `stop` refuses to break active required consumers; selective `start` does not invent or auto-start missing providers.

## Shell completion

Bash/Zsh completion is manifest-aware and source-local. Candidate calculation does not query Docker or registries. Bash/Zsh adapters can be generated without mutation. `completion install` detects the shell from `$SHELL`, chooses the implemented root/user target, writes the generated adapter idempotently and does not rewrite shell startup files. `completion status` verifies the target file/content. Actual loading still depends on the shell's own completion configuration (`bash-completion` for the Bash user directory; `fpath`/completion initialization for Zsh), so installed-file state is not claimed as proof that every interactive shell loads it.

Completion follows the same public grammar as the CLI: lifecycle and upgrade stack candidates are numeric `0` through `7`; upgrade target actions are `select`/`clear`; policy mutation actions are `set`/`clear`, while policy inspection is action-less.
