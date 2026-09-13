# Pending work

Only active or intentionally deferred work belongs here. Completed qualification details live in `docs/dr/status.md` or Git history, not as a second backlog.

## P0 — DR operational hardening

- Define backup encryption-at-rest, retention generations, off-host copy and verification policy.
- Package/document the external Stack6 memory-sync SSH bootstrap required when the configured Git origin needs that credential.

## P1 — Management CLI and upgrades

- `./local-ai` is the sole supported management boundary; keep internal Python, shell, Compose and DR paths outside the external contract.
- Add selective stack runtime lifecycle operations through `./local-ai` so operators can stop and start an individual stack without calling Docker Compose directly. The CLI should act as the supported intermediary for semantics equivalent to a controlled `docker compose stop` / `docker compose start`, resolve the stack from project manifests, preserve dependency/state ownership rules, avoid implicit destructive actions, and expose coherent human/JSON results. This is not currently implemented.
- Keep container version discovery bound to the registry/repository named by each configured image. Human versions come from tags published for that exact registry package; immutable digests remain machine identity. Do not reintroduce lateral GitHub Release lookups for container inventory.
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

Project support/compatibility policy above registry discovery is implemented: catalog defaults plus installation-local overrides define effective `minor-series`, `major-series` or `manual` policy; selection and apply both revalidate policy and immutable target identity; policy changes do not silently delete selections; and major movement is never inferred merely because a registry publishes a newer tag.

The mutable-tag status regression is now closed and permanently covered. Runtime qualification on m92p proved that `status` and `upgrade check` agree on concrete runtime identity for registry-backed floating tags: HAProxy reports Actual `3.0.26-alpine3.24` versus Desired `3.0.27-alpine3.24` with `DRIFT=yes`; Redis reports Actual `8.10.0-alpine3.23` versus Desired `8.10.1-alpine3.23` with `DRIFT=yes`; RabbitMQ reports matching `3.13.7-alpine` with `DRIFT=no`. Permanent tests cover moved floating tags, unchanged floating tags, fixed semantic tags, digest-pinned images, cross-command Actual consistency and fail-closed behavior when registry resolution is unavailable. OpenSpec contract `CLI-STATUS-003` traces these invariants. Focused status tests, OpenSpec tests, the full repository suite, live `status` and live `upgrade check` all passed; the active checkout finished with zero Python cache artifacts and zero tracked worktree changes.

Stack1 landing-page and public agent naming are migrated and runtime-qualified: Open WebUI is exposed from the CASA.LAN landing page at `chat.casa.lan`; the former AgentIA route/variables/CORS identity are replaced by `NorAI`, `norai.casa.lan`, `NORAI_HOSTNAME`, `NORAI_TARGET` and `https://norai.casa.lan`; HAProxy routes NorAI to `hermes:9119`; Hermes was recreated with the new CORS origin and returned healthy; both NorAI and Open WebUI HTTPS routes passed; the old `agentia.casa.lan` hostname now falls through to the default landing backend instead of selecting an agent backend.

The Stack6 READY lifecycle invocation defect discovered during that migration is fixed in source: `07-wait-ready.sh` is invoked explicitly through `bash` because the tracked file is not executable. Regression coverage now asserts the Stack6 lifecycle command and, generically, that every lifecycle command invoked directly as `./script` points to an executable file. OpenSpec `INSTALL-LIFECYCLE-001` states that lifecycle scripts must either be directly executable or invoked through an explicit interpreter.

The initial discovery layer proved same-tag digest comparison, Docker Hub repository normalization and explicit remote failure reporting. ADR-0003 now defines a stricter single-source rule: container inventory follows the image reference to its own registry package, uses human tags from that package for operator-facing versions, and preserves the digest as immutable artifact identity. The previous GitHub Release adapters and explicit cross-source registry hints have been removed from the component catalog. Runtime qualification of this registry-native tag-to-digest mapping is the next gate.

`local-ai` is operationally proven for the guarded single-component upgrade path used by Hermes. Broader upgrade coverage still depends on project-supported target policy and component-specific migration contracts where required.
