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

## P1 — Version authority closeout

- Resolve the Stack4 Gitea runner's legacy `docker.io/gitea/runner:3` tracking reference into an exact installation-owned identity before claiming complete component image authority. Capture the deployed runtime identity first; do not advance it from remote registry discovery.
- Decide whether fixed support sidecars such as Stack1 `busybox:1.38.0` belong in upgrade inventory or remain explicitly outside the operator upgrade catalog. Exact fixed sidecars must not become moving registry channels.

## P2 — Operations

- Define retention and cleanup treatment for historical local backup sets; verified recovery evidence must not be deleted incidentally.
- Define an operator-owned cleanup policy for migration dumps, migration markers and destructive-recovery test material without embedding host-specific absolute paths or temporary artifact names in repository documentation.
