# Pending Work

This is the project-wide backlog of work explicitly deferred or left incomplete in the Local Hybrid AI design conversations. Completed items should be removed or moved to Git history when closed; do not turn this into a historical changelog.

## P0 — DR completion

- **Qualify the Stack6 portable-memory verifier on the reference host.** `dr_stack6_verify.py` now defines the read-only proof for the only durable Stack6 exception: Git-backed `MEMORY.md` + `USER.md`. Run its focused tests and real verifier after synchronizing the host; once it passes, Stack6 has no remaining data-backup gap.
- **Protected `.env` DR policy.** `.env` is a required global recovery prerequisite and contains persistent identity such as `LITELLM_SALT_KEY`, but the engine currently does not create a protected copy. Decide encrypted backup mechanism, storage, rotation and restore procedure without exposing values.
- **Backup encryption, retention and off-host policy.** `/opt/local-hybrid-ai-backups` is currently local/staging. Define encryption-at-rest, retention generations, off-host copy and verification policy.
- **Generic real `backup all`.** Integrate already-proven Stack0/Stack3/Stack4 adapters through the generic manifest-driven engine rather than stack-number conditionals. Stack6 contributes no backup artifact; its externalized Git memory is a prerequisite verified separately.
- **Clean-environment restore drill.** Rebuild into an isolated/temporary clean environment from Git + protected `.env` + PKI + LiteLLM dump + Gitea dump, then restore/reconnect portable user memory. Do not destroy the current host without explicit authorization.

## P1 — DR engine hardening

- Reject backup destination equal to or below `STACKS_ROOT` or `BASE_PATH`, and reject source/destination overlap before real backup execution.
- Harden `stack0_-_platform/manifests.py` recovery validation against malformed non-string `mode`, `class` and `strategy` values instead of allowing membership operations to raise `TypeError`.
- Reject boolean `schema_version` explicitly (`True == 1` in Python must not validate as schema version 1).
- Harden/retire the older `dr_archive.py` post-publication verification path so every adapter performs all fallible integrity checks before the terminal atomic publication step.
- Add direct unit tests for Stack4 helper failure paths: dump failure, restart failure, health timeout, helper cleanup failure and combined failure handling.
- Replace the temporary `bkp-dr` compatibility symlinks/project-root assumptions with an explicit project-root resolver so DR code can live cleanly under `bkp-dr` without filesystem aliases.

## P1 — Installer/platform hardening

- Add explicit configuration/version drift detection. Current installer state observation can treat an already healthy running stack as converged even when tracked Compose/config changed. Design an explicit `--converge`/`--upgrade` model rather than silently recreating services.
- Add a common-installer concurrency lock so two installer executions cannot mutate lifecycle state concurrently.
- Decide whether the current explicit Stack4 `04-gitmem` operation should remain outside the common installer permanently or gain a normalized lifecycle representation.
- Keep `.lock` semantics unchanged: PREPARED only, never deployed/healthy/ready.

## P2 — Next stack

- **Open WebUI** remains the next planned independent atomic stack. Before implementation define stack ID/directory, ownership, persistence/database model, required and optional dependencies, consumed/provided capabilities, secret provenance, readiness, Stack1 ingress relationship, recovery contract, tests and documentation. Do not add Open-WebUI-specific branches to generic installer/DR engines when manifests can express the relationship.

## P2 — Operational follow-up

- Decide whether historical local backup sets should eventually be retained, rotated or moved off-host. Do not delete the verified Stack0/Stack3/Stack4 sets as generic cleanup.
- The Stack3 migration rollback dump under `/root/litellm-postgres-migration-20260908-150526/litellm.dump` is operator-owned cleanup. The operator has stated that `/root` cleanup will be handled manually; automation must not remove it.
- Review the historical runtime marker `/opt/docker/runtime/service_-_litellm-postgres/.migration-from-stack2-complete`; it is no longer part of normal installation, but deletion should be a separate bounded cleanup decision after confirming no code depends on it.

## Closed in the latest DR iteration

The Stack6 persistence boundary is now explicit: Hermes and the complete sandbox/runtime are replaceable and reconstructable. `SOUL.md` is runtime-generated Nous Research behavior text and is not a DR resource. Hermes SQLite databases, caches, packages, sessions, logs and sandbox state are disposable. The only durable application-level exception is the externalized Git-backed user memory contract (`MEMORY.md` + `USER.md`). No further Hermes-runtime externalization is planned.

The Stack4 Gitea adapter no longer treats rootless operation as part of the DR contract. It discovers the deployed execution context before the controlled stop, has synthetic rootless/rootful coverage, and the current rootless deployment passed a real controlled-offline backup plus isolated restore regression with the generic-context implementation. Future deployment variants must still pass preflight discovery unambiguously; no rootless-specific follow-up remains open.

The post-reorganization validation/cleanup pass has also completed successfully on the reference host: manifests validated, installer tests passed, the complete current DR test suite passed from `bkp-dr/tests`, `install.py all --dry-run` converged, critical services remained healthy, generated Python/restore test debris was cleaned, no Gitea dump helper remained, the Git worktree was clean, and local HEAD matched `origin/main` at the time of validation.