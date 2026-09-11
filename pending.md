# Pending Work

This is the project-wide backlog of work explicitly deferred or left incomplete in the Local Hybrid AI design conversations. Completed items should be removed or moved to Git history when closed; do not turn this into a historical changelog.

## P0 — DR completion

- **Generic `restore all` execution.** The read-only planner, isolated filesystem staging, and isolated managed-state reconstruction are now host-qualified against the canonical recovery point. Stack3 restored 75 PostgreSQL tables (25 non-empty) into a disposable PostgreSQL container; Stack4 rebuilt its SQLite database with 116 tables (38 non-empty), validated 8 repositories, and successfully started an isolated healthy Gitea instance. Drill containers used no published ports or platform network and were removed; production container identities and health remained unchanged. The next bounded step is the new end-to-end isolated recovery drill (`bkp-dr/dr_restore_drill.py` / `restore-drill.py`) from a fresh destination, then lifecycle PREPARE/DEPLOY/VERIFY in a genuinely isolated clean target. Do not enable live-host mutation before clean-target qualification.
- **Clean-environment lifecycle restore drill.** After the end-to-end artifact/state drill passes, prove PREPARE/DEPLOY/READY/VERIFY for reconstructed stacks in an isolated Docker environment. Do not destroy or repurpose the current reference host without explicit authorization.
- **Backup encryption, retention and off-host policy.** `/opt/local-hybrid-ai-backups` is currently local/staging. ADR-0001 deliberately accepts plaintext `.env` inside the private backup set for now; define encryption-at-rest, retention generations, off-host copy and verification policy as later hardening.

## P1 — DR engine hardening

- Reject backup destination equal to or below `STACKS_ROOT` or `BASE_PATH`, and reject source/destination overlap before real backup execution.
- Harden `stack0_-_platform/manifests.py` recovery validation against malformed non-string `mode`, `class` and `strategy` values instead of allowing membership operations to raise `TypeError`.
- Reject boolean `schema_version` explicitly (`True == 1` in Python must not validate as schema version 1).
- Harden/retire the older `dr_archive.py` post-publication verification path so every adapter performs all fallible integrity checks before the terminal atomic publication step.
- Add direct unit tests for Stack4 helper failure paths: dump failure, restart failure, health timeout, helper cleanup failure and combined failure handling.
- Replace the temporary `bkp-dr` compatibility symlinks/project-root assumptions with an explicit project-root resolver so DR code can live cleanly under `bkp-dr` without filesystem aliases.
- Refactor the managed restore drill so strategy adapters are registered generically rather than relying on resource-id-specific helper calls; preserve the current no-stack-number-special-cases rule in orchestration.

## P1 — Installer/platform hardening

- Add explicit configuration/version drift detection. Current installer state observation can treat an already healthy running stack as converged even when tracked Compose/config changed. Design an explicit `--converge`/`--upgrade` model rather than silently recreating services.
- Add a common-installer concurrency lock so two installer executions cannot mutate lifecycle state concurrently.
- Decide whether the current explicit Stack4 `04-gitmem` operation should remain outside the common installer permanently or gain a normalized lifecycle representation.
- Keep `.lock` semantics unchanged: PREPARED only, never deployed/healthy/ready.

## P2 — Next stack

- **Open WebUI** remains the next planned independent atomic stack. Before implementation define stack ID/directory, ownership, persistence/database model, required and optional dependencies, consumed/provided capabilities, secret provenance, readiness, Stack1 ingress relationship, recovery contract, tests and documentation. Do not add Open-WebUI-specific branches to generic installer/DR engines when manifests can express the relationship.

## P2 — Operational follow-up

- Decide whether historical local backup sets should eventually be retained, rotated or moved off-host. Do not delete the verified Stack0/Stack3/Stack4/full sets as generic cleanup.
- The Stack3 migration rollback dump under `/root/litellm-postgres-migration-20260908-150526/litellm.dump` is operator-owned cleanup. The operator has stated that `/root` cleanup will be handled manually; automation must not remove it.
- Review the historical runtime marker `/opt/docker/runtime/service_-_litellm-postgres/.migration-from-stack2-complete`; it is no longer part of normal installation, but deletion should be a separate bounded cleanup decision after confirming no code depends on it.

## Closed in the latest DR iteration

The generic real `backup all` path and its exact stored recovery point are fully qualified on the reference host. Canonical set: `/opt/local-hybrid-ai-backups/backup-20260911T004927Z`, created from source commit `f732f0e1bca533556d9a60fef5bd373b51675da2`.

Creation detected deployed stacks 0-6 from the validated installer lifecycle/manifest ownership contract, included the protected operational `.env` as a global sensitive artifact per ADR-0001, created Stack0 PKI, Stack3 LiteLLM custom PostgreSQL dump and Stack4 controlled-offline Gitea native dump inside one private temporary recovery set, preserved Stack6 as an external Git prerequisite, and published atomically. Gitea returned healthy, no dump helper remained and Git ended clean.

The exact same set passed stored-artifact recovery qualification: all checksums passed; Stack0 PKI isolated extraction/fingerprint matched; Stack3 restored 75/75 tables with 25 non-empty tables; Stack4 restored 116 SQLite tables with 38 non-empty tables and 8/8 repositories passed `git fsck`; the backed-up operational `.env` SHA-256 matched the protected file; Stack6 external Git memory verification passed; live services remained unchanged/healthy; Git ended clean.

The generic read-only `restore all` planner is implemented and host-qualified. Isolated filesystem staging is also host-qualified: recorded source commit, protected `.env` mode `0600`, external-config prerequisite, and Stack0 PKI were reconstructed outside live runtime.

The isolated managed-state drill is now host-qualified as well. From the canonical backup it restored Stack3 into a new disposable PostgreSQL container (75 tables, 25 non-empty), rebuilt Stack4's **SQLite** database from `gitea-db.sql` (116 tables, 38 non-empty), validated 8 Git repositories, and started an isolated healthy Gitea. No ports were published, no drill service joined the platform network, drill containers were removed, the canonical backup checksums remained valid, production Gitea/LiteLLM container identities remained unchanged, production services stayed healthy, and Git ended clean at `a26be49a71b1747104f6024675ea0c83c6570c5c`.

The distinction is explicit: Stack3/LiteLLM uses PostgreSQL; Stack4/Gitea uses SQLite plus filesystem/repositories. PostgreSQL is not part of the Gitea recovery path.

The Stack6 persistence boundary remains explicit: Hermes and the complete sandbox/runtime are replaceable and reconstructable. `SOUL.md` is runtime-generated Nous Research behavior text and is not a DR resource. The only durable application-level exception is the externalized Git-backed user memory contract (`MEMORY.md` + `USER.md`). The Git remote may be Gitea, another Git service/SaaS, or another configured repository; Stack6 does not acquire a required Stack4 dependency from DR.

ADR-0001 records the accepted compromise that the protected operational `.env` is included directly in complete backup sets until a better secret-recovery mechanism exists.
