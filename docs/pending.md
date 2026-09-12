# Pending work

Only active or intentionally deferred work belongs here. Completed qualification details live in `docs/dr/status.md` or Git history, not as a second backlog.

## P0 — DR operational hardening

- Define backup encryption-at-rest, retention generations, off-host copy and verification policy.
- Package/document the external Stack6 memory-sync SSH bootstrap required when the configured Git origin needs that credential.

## P1 — DR engine hardening

- Reject backup destinations equal to/below `STACKS_ROOT` or `BASE_PATH`, and reject source/destination overlap before execution.
- Harden recovery validation for malformed non-string `mode`, `class` and `strategy` values.
- Reject boolean `schema_version` explicitly.
- Ensure every adapter completes fallible integrity checks before terminal atomic publication.
- Add Stack4 helper failure-path tests (dump/restart/health/helper cleanup/combined failure).
- Replace compatibility symlink/project-root assumptions with an explicit project-root resolver.
- Move managed restore dispatch toward a generic adapter registry without stack-number special cases.
- Normalize global-artifact access around `resource_id`.
- Keep bounded/resumable recovery fail-closed; never blindly re-import managed state after a late failure.

## P1 — Installer/platform hardening

- Add explicit source/configuration drift detection and design a deliberate `--converge` / `--upgrade` model rather than silently recreating healthy services.
- Add a common installer concurrency lock.
- Decide whether Stack4 `04-gitmem` remains an explicit operation or gains a normalized lifecycle representation.
- Keep `.lock` semantics as PREPARED only.

## P2 — Operations

- Define retention/cleanup treatment for historical local backup sets; verified evidence must not be deleted incidentally.
- `/root/litellm-postgres-migration-20260908-150526/litellm.dump` remains operator-owned cleanup material.
- Historical migration markers and destructive-recovery test material require separate explicit cleanup decisions.

## Recently closed

Stack7/Open WebUI base, web capability, regular-user model policy and first global DR point are qualified. Core `backup all` plus clean-target `restore all` for the pre-Stack7 platform is qualified. Stack6 Buzz is reconstructable from pinned source. Repository tests/documentation/specification are now being normalized under `tests/`, `docs/`, `adr/`, `sdr/` and `openspec/`.

The next design conversation after repository normalization is intentionally **operator UX**: one human-facing model for install, status/doctor, backup, restore and component upgrades/version changes on a running installation. Do not implement that interface before agreeing the design.
