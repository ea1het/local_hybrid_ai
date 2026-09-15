<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Pending work

Only active or intentionally deferred work belongs here. Completed work and implementation chronology belong in Git history; durable behaviour belongs in architecture, specification, user/developer documentation and qualification evidence.

## P0 — DR operational hardening

- Define backup encryption-at-rest, retention generations, off-host copy and verification policy.
- Package and document the external Stack6 memory-sync SSH bootstrap required when the configured Git origin needs that credential.

## P1 — DR engine hardening

- Harden recovery validation for malformed non-string `mode`, `class` and `strategy` values.
- Reject boolean `schema_version` explicitly rather than accepting Python's `True == 1` equivalence.
- Ensure every adapter completes fallible integrity checks before terminal atomic publication.
- Add Stack4 helper failure-path tests covering dump, restart, health, helper cleanup and combined failure.
- Replace compatibility symlink/project-root assumptions with an explicit project-root resolver.
- Move managed restore dispatch toward a generic adapter registry without stack-number special cases.
- Normalize global-artifact access around `resource_id`.
- Keep bounded/resumable recovery fail-closed; never blindly re-import managed state after a late failure.

## P1 — Installer/platform hardening

- Add a common installer concurrency lock.
- Decide whether Stack4 `04-gitmem` remains an explicit operation or gains a normalized lifecycle representation.
- Keep `.lock` semantics as PREPARED only.

## P1 — CLI completion correctness and specification

- Align `start`/`stop` TAB candidates with the documented human numeric stack identifiers (`0` through `7`); the current completion engine emits `stackN` candidates even though numeric identifiers are the primary human contract.
- Reconcile upgrade-policy completion with the actual grammar. The current completion engine advertises `show` after `upgrade policy <stack> <component>` although the documented/operator grammar uses inspection with no action plus `set` and `clear`.
- Add stable OpenSpec tags for completion candidate semantics, source-only completion boundaries and persistent Bash/Zsh installation, then map those tags in `openspec/traceability.md` to `tests/test_completion.py` and runtime qualification where applicable.
- Add documentation-contract coverage ensuring every public top-level `local-ai` command, including `completion`, is represented in the CLI command map and canonical TOC.

## P2 — Operations

- Define retention and cleanup treatment for historical local backup sets; verified recovery evidence must not be deleted incidentally.
- Define an operator-owned cleanup policy for migration dumps, migration markers and destructive-recovery test material without embedding host-specific absolute paths or temporary artifact names in repository documentation.

## P2 — Documentation maintenance

- Keep [current-state.md](current-state.md) synchronized when a public command family, component-authority rule or implementation root is added/retired.
- During future structural migrations, search canonical docs for retired path/command names and retain them only in ADR/history/restore-compatibility context where the historical reference is intentional.
