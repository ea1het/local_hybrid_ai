# Pending work

Only active or intentionally deferred work belongs here. Completed qualification details live in `docs/dr/status.md` or Git history, not as a second backlog.

## Immediate handoff — status/registry identity regression coverage

The current `main` runtime behavior is qualified on m92p after the status identity fix: the full suite passed **277 tests**, `./local-ai status` and `./local-ai upgrade check` both completed successfully, Python cache count was zero and the tracked worktree was clean.

A real runtime gap was discovered even though the prior suite was green: `status` used to compare image tag text while `upgrade check` resolved registry-backed image identity. Mutable/partially floating tags could therefore report false `DRIFT=no`. Runtime evidence exposed this with:

- HAProxy: configured tracking reference `3.0-alpine`; Actual `3.0.26-alpine3.24`; current registry Desired `3.0.27-alpine3.24`; `DRIFT=yes`.
- Redis: configured tracking reference `redis:alpine`; Actual `8.10.0-alpine3.23`; current registry Desired `8.10.1-alpine3.23`; `DRIFT=yes`.
- RabbitMQ: configured tracking reference `3-alpine`; Actual and resolved Desired both `3.13.7-alpine`; `DRIFT=no`.

The implementation now resolves floating registry-backed identities for `status`, compares immutable digest evidence when available, keeps `status` and `upgrade check` aligned on runtime identity, and fails closed to `DRIFT=n/a` when registry evidence required for a floating reference cannot be established. This must now be protected with permanent regression tests rather than relying on ad-hoc live qualification.

The next agent should add regression coverage for these invariants, without special-casing Redis, HAProxy or RabbitMQ in production code:

1. A floating tag whose local digest maps to version A while the current registry tracking tag maps to version B must produce `Desired=B`, `Actual=A`, and `Drift=yes`.
2. A floating tag whose local and remote identities are the same must produce `Drift=no`.
3. A pinned semantic tag must retain deterministic status behavior without unnecessary reinterpretation.
4. A digest-pinned image must compare immutable identity correctly.
5. For every registry-backed component, `status.actual` and `upgrade check.actual` must be derived from the same runtime image/normalization semantics.
6. If required registry resolution is unavailable for a floating reference, `status` must not synthesize `Drift=no`; the result must fail closed according to the current `yes` / `no` / `n/a` contract.
7. Pre-history deployment adoption must remain separate from drift resolution: successful guarded-upgrade history remains authoritative for `DEPLOYED`; otherwise the observed runtime identity is the adoption baseline.

Prefer focused tests in `tests/test_status.py` plus cross-boundary/registry fixtures where necessary. Reuse existing `commands.upgrade_registry` probe semantics instead of duplicating registry parsing logic in tests. After focused coverage passes, run the complete suite with `PYTHONDONTWRITEBYTECODE=1` and verify zero tracked changes and zero Python cache artifacts.

## P0 — DR operational hardening

- Define backup encryption-at-rest, retention generations, off-host copy and verification policy.
- Package/document the external Stack6 memory-sync SSH bootstrap required when the configured Git origin needs that credential.

## P1 — Management CLI and upgrades

- `./local-ai` is the sole supported management boundary; keep internal Python, shell, Compose and DR paths outside the external contract.
- Keep container version discovery bound to the registry/repository named by each configured image. Human versions come from tags published for that exact registry package; immutable digests remain machine identity. Do not reintroduce lateral GitHub Release lookups for container inventory.
- Add an explicit project support/compatibility policy above registry discovery. A newer registry tag is only a discovered candidate; it must not become selectable or executable merely because it exists. Major-version movement requires explicit project policy.
- Runtime-qualify registry tag/digest mapping across Docker Hub, GHCR and `docker.gitea.com`, including rate-limit/authentication failure states and digest-only pins such as Firecrawl.
- Add bounded cache/TTL handling for remote registry discovery so repeated `upgrade check` calls do not waste rate-limit budget.
- Extend safe execution metadata to components that are currently inventory-only/non-selectable because their version is pinned directly in tracked Compose or needs a component-specific migration contract. LiteLLM remains non-selectable until its compatibility and migration policy are explicit.
- Complete stable JSON contracts for install/doctor/restore where not yet exposed.
- Add doctor through `local-ai` rather than a new public script.

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

Stack7/Open WebUI base, web capability, regular-user model policy and first global DR point are qualified. Core `backup all` plus clean-target `restore all` for the pre-Stack7 platform is qualified. Stack6 Buzz is reconstructable from pinned source. Repository tests/documentation/specification are normalized under `tests/` and `docs/`, with ADR, SDR and OpenSpec material under the developer documentation tree.

The guarded upgrade executor is live-qualified on Stack6/Hermes: `v2026.8.31 -> v2026.9.11` was selected explicitly, the exact target image preflight passed, only Hermes was deployed, Stack6 returned READY, capability reconciliation completed, VERIFY passed, the running image was confirmed at the selected target, prepared consumer Stack1 was reverified, and the selection was cleared only after success. The qualification completed with all command return codes at zero. Stack6 remains reconstructable; only Git-backed `MEMORY.md` + `USER.md` is durable user memory, so Hermes sessions/SQLite/cache state are not upgrade recovery requirements.

Upgrade application is serialized at the `local-ai` boundary with a non-blocking runtime lock and failed applications are appended to the upgrade history with stable error code, selection snapshot and recovery point when present. `local-ai status` exposes installation Desired, best-known Deployed and runtime Actual state separately. Successful guarded-upgrade history is authoritative for Deployed; installations predating that history use observed Actual as their adoption baseline. Drift is a quick Desired-versus-Actual decision with only `yes`, `no` and `n/a`. An upgrade selection remains a plan and is not silently promoted to desired or deployed state.

The initial discovery layer proved same-tag digest comparison, Docker Hub repository normalization and explicit remote failure reporting. ADR-0003 now defines a stricter single-source rule: container inventory follows the image reference to its own registry package, uses human tags from that package for operator-facing versions, and preserves the digest as immutable artifact identity. The previous GitHub Release adapters and explicit cross-source registry hints have been removed from the component catalog. Runtime qualification of this registry-native tag-to-digest mapping is the next gate.

`local-ai` is operationally proven for the guarded single-component upgrade path used by Hermes. Broader upgrade coverage still depends on project-supported target policy and component-specific migration contracts where required.
