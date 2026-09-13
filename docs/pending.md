# Pending work

Only active or intentionally deferred work belongs here. Completed qualification details live in `docs/dr/status.md` or Git history, not as a second backlog.

## P0 — DR operational hardening

- Define backup encryption-at-rest, retention generations, off-host copy and verification policy.
- Package/document the external Stack6 memory-sync SSH bootstrap required when the configured Git origin needs that credential.

## P1 — Management CLI and upgrades

- `./local-ai` is the sole supported management boundary; keep internal Python, shell, Compose and DR paths outside the external contract.
- Define validated version-source adapters per component. `Available` must distinguish a usable/tested upgrade candidate from merely the latest reachable upstream release. LiteLLM remains non-selectable until its release-tag/container-tag mapping and compatibility policy are explicit.
- Extend safe execution metadata to components that are currently inventory-only/non-selectable because their version is pinned directly in tracked Compose or needs a component-specific migration contract.
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

The guarded upgrade executor is live-qualified on Stack6/Hermes: `v2026.8.31 -> v2026.9.11` was selected explicitly, the exact target image preflight passed, only Hermes was deployed, Stack6 returned READY, capability reconciliation completed, VERIFY passed, the running image was confirmed at the selected target, prepared consumer Stack1 was reverified, and the selection was cleared only after success. Stack6 remains reconstructable; only Git-backed `MEMORY.md` + `USER.md` is durable user memory.

Upgrade application is now serialized at the sole public `local-ai` boundary with a non-blocking process lock. A concurrent `upgrade --yes` fails closed as `UPGRADE_BUSY`; failed apply attempts are appended to the same installation-local JSONL history with the selected plan snapshot and stable error code. This does not alter stack `.lock` semantics. Broader upgrade coverage still depends on validated per-component version adapters, component-specific migration contracts where required, and explicit desired/deployed/actual drift handling.
