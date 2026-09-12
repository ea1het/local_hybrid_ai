# Pending work

Only active or intentionally deferred work belongs here. Completed qualification details live in `docs/dr/status.md` or Git history, not as a second backlog.

## P0 — DR operational hardening

- Define backup encryption-at-rest, retention generations, off-host copy and verification policy.
- Package/document the external Stack6 memory-sync SSH bootstrap required when the configured Git origin needs that credential.

## P1 — Management CLI and upgrades

- `./local-ai` is now the sole supported management boundary; keep internal Python, shell, Compose and DR paths outside the external contract.
- Finish the safe upgrade executor behind the installation-local selection plan. `upgrade check` and `select` exist first; execution must not be enabled until backup, rollback/recovery and dependency reverification rules are wired in.
- Define validated version-source adapters per component. `Available` must distinguish a usable upgrade candidate from an unreachable/unknown upstream source.
- Add deployed-state/history records without changing `.lock` semantics.
- Add explicit source/runtime drift detection and make drift distinct from selected upgrade intent.
- Complete stable JSON contracts for install/status/doctor/restore where not yet exposed.
- Add status and doctor operator commands through `local-ai` rather than new public scripts.

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

- Add a common installer concurrency lock.
- Decide whether Stack4 `04-gitmem` remains an explicit operation or gains a normalized lifecycle representation.
- Keep `.lock` semantics as PREPARED only.

## P2 — Operations

- Define retention/cleanup treatment for historical local backup sets; verified evidence must not be deleted incidentally.
- `/root/litellm-postgres-migration-20260908-150526/litellm.dump` remains operator-owned cleanup material.
- Historical migration markers and destructive-recovery test material require separate explicit cleanup decisions.

## Recently closed

Stack7/Open WebUI base, web capability, regular-user model policy and first global DR point are qualified. Core `backup all` plus clean-target `restore all` for the pre-Stack7 platform is qualified. Stack6 Buzz is reconstructable from pinned source. Repository tests/documentation/specification are normalized under `tests/`, `docs/`, `adr/`, `sdr/` and `openspec/`.

The operator UX design has moved into implementation: `local-ai` is the anticorruption boundary and the installation-local upgrade plan exposes a complete component inventory with Current, Available and Selected state. The destructive upgrade executor remains intentionally disabled until its recovery semantics are implemented and qualified.
