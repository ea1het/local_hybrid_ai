<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Pending work

Only active or intentionally deferred work belongs here. Completed work and detailed qualification chronology belong in Git history; durable contracts and qualification status belong in their canonical architecture, specification, testing or recovery documents.

## P0 — DR operational hardening

- Define backup encryption-at-rest, retention generations, off-host copy and verification policy.
- Package and document the external Stack6 memory-sync SSH bootstrap required when the configured Git origin needs that credential.

## P1 — Management CLI and upgrades

- `./local-ai` is the sole supported management boundary; keep internal Python, shell, Compose and DR paths outside the external contract.
- Keep container version discovery bound to the registry/repository named by each configured image. Human versions come from tags published for that exact registry package; immutable digests remain machine identity. Do not reintroduce lateral GitHub Release lookups for container inventory.
- Add bounded cache/TTL handling for remote registry discovery so repeated `upgrade check` calls do not waste rate-limit budget.
- Extend safe execution metadata to components that are currently inventory-only/non-selectable because their version is pinned directly in tracked Compose or needs a component-specific migration contract. LiteLLM remains non-selectable until its compatibility and migration policy are explicit.
- Complete stable JSON contracts for install/doctor/restore where not yet exposed.
- Add doctor through `local-ai` rather than a new public script.

## P1 — DR engine hardening

- Harden recovery validation for malformed non-string `mode`, `class` and `strategy` values.
- Reject boolean `schema_version` explicitly.
- Ensure every adapter completes fallible integrity checks before terminal atomic publication.
- Add Stack4 helper failure-path tests (dump/restart/health/helper cleanup/combined failure).
- Replace compatibility symlink/project-root assumptions with an explicit project-root resolver.
- Move managed restore dispatch toward a generic adapter registry without stack-number special cases.
- Normalize global-artifact access around `resource_id`.
- Keep bounded/resumable recovery fail-closed; never blindly re-import managed state after a late failure.

## P1 — Installer/platform hardening

- Add a common installer concurrency lock.
- Decide whether Stack4 `04-gitmem` remains an explicit operation or gains a normalized lifecycle representation.
- Keep `.lock` semantics as PREPARED only.

## P2 — Operations

- Define retention and cleanup treatment for historical local backup sets; verified recovery evidence must not be deleted incidentally.
- Define an operator-owned cleanup policy for migration dumps, migration markers and destructive-recovery test material without embedding host-specific absolute paths or temporary artifact names in repository documentation.
