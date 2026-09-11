# Pending Work

This is the project-wide backlog of work explicitly deferred or left incomplete in the Local Hybrid AI design conversations. Completed items should be removed from active backlog rather than leaving obsolete next steps.

## P0 — DR operational hardening

- **Backup encryption, retention and off-host policy.** `/opt/local-hybrid-ai-backups` is currently local/staging. ADR-0001 deliberately accepts plaintext `.env` inside the private backup set for now; define encryption-at-rest, retention generations, off-host copy and verification policy.
- **External recovery prerequisites.** Document/operator-package the Stack6 memory-sync SSH bootstrap needed when the configured portable-memory Git origin requires it. It remains an external prerequisite rather than a Hermes application backup artifact.

The core `backup all` + `restore all` path is no longer pending: it has passed a real destructive clean-target recovery of the reference host.

## P1 — DR engine hardening

- Reject backup destination equal to or below `STACKS_ROOT` or `BASE_PATH`, and reject source/destination overlap before real backup execution.
- Harden recovery validation against malformed non-string `mode`, `class` and `strategy` values instead of allowing membership operations to raise `TypeError`.
- Reject boolean `schema_version` explicitly (`True == 1` in Python must not validate as schema version 1).
- Harden/retire older archive post-publication verification so every adapter performs all fallible integrity checks before terminal atomic publication.
- Add direct unit tests for Stack4 helper failure paths: dump failure, restart failure, health timeout, helper cleanup failure and combined failure handling.
- Replace temporary `bkp-dr` compatibility symlinks/project-root assumptions with an explicit project-root resolver.
- Refactor managed restore strategy dispatch toward a generic adapter registry while preserving the no-stack-number-special-cases orchestration rule.
- Normalize the global-artifact accessor around schema field `resource_id`; destructive recovery exposed historical `id`/`resource_id` compatibility assumptions in recovery tooling.
- Keep bounded/resumable recovery fail-closed. Do not blindly re-import Stack3/Stack4 managed state after a late lifecycle failure.

## P1 — Installer/platform hardening

- **READY after restart-causing RECONCILE.** Destructive recovery exposed a historical Stack6 race: Hermes could be recreated by reconcile and immediately observed as `running/starting`. Ensure the current generic lifecycle waits for required runtime readiness after any reconcile that restarts/recreates required services before final VERIFY.
- Add explicit configuration/version drift detection. Current installer state observation can treat an already healthy running stack as converged even when tracked Compose/config changed. Design an explicit `--converge`/`--upgrade` model rather than silently recreating services.
- Add a common-installer concurrency lock so two installer executions cannot mutate lifecycle state concurrently.
- Decide whether the current explicit Stack4 `04-gitmem` operation should remain outside the common installer permanently or gain a normalized lifecycle representation.
- Keep `.lock` semantics unchanged: PREPARED only, never deployed/healthy/ready.

## P2 — Next stack

- **Open WebUI** remains the next planned independent atomic stack. Before implementation define stack ID/directory, ownership, persistence/database model, required and optional dependencies, consumed/provided capabilities, secret provenance, readiness, Stack1 ingress relationship, recovery contract, tests and documentation. Do not add Open-WebUI-specific branches to generic installer/DR engines when manifests can express the relationship.

## P2 — Operational follow-up

- Decide whether historical local backup sets should eventually be retained, rotated or moved off-host. Do not delete verified recovery evidence as generic cleanup.
- The Stack3 migration rollback dump under `/root/litellm-postgres-migration-20260908-150526/litellm.dump` is operator-owned cleanup. Automation must not remove it.
- Review any historical migration marker only as a separate bounded cleanup decision after confirming no code depends on it.
- The destructive recovery test directories/checkouts and historical backup sets should be cleaned only by an explicit operator-approved retention decision, not as incidental installer/DR cleanup.

## Closed — core DR recovery path

A fresh pre-wipe recovery point was created at:

```text
/opt/local-hybrid-ai-backups/backup-20260911T172551Z
source_commit = 7cbfa2874f6e865a4de6e2854b2589de52a39913
```

The operator explicitly authorized a destructive clean-target proof. Platform containers/reconstructable Docker objects were removed and `/opt/docker` was destroyed. Recovery tooling lived outside the target and reconstructed the platform from the recorded recovery point/source commit.

The exercise exposed and fixed recovery-tooling issues (`resource_id` global-artifact lookup, byte-exact restored-source verification) plus a historical Stack6 readiness race. A bounded resume then passed without another wipe or blind database re-import.

Final recovery evidence:

- resolved stacks 0-6;
- LiteLLM PostgreSQL: 75 tables;
- Gitea: 116 SQLite tables and 8 validated repositories;
- portable memory HEAD `e9c220aa26b29303a18fa4b3f43f1c6edc0760ca`;
- Stack6 `hermes-memory-sync` returned running;
- all expected containers returned running/healthy where healthchecks exist;
- recovery-point checksums remained valid;
- restored source matched the recorded source commit byte-for-byte.

Therefore core `backup all` + clean-target `restore all` is functionally qualified. Remaining DR items are hardening/operations rather than an unproven recovery path.

## Closed — Stack6 Buzz reconstruction

The destructive wipe revealed that Buzz had historically been compiled from GitHub and manually copied into Hermes runtime. That implicit dependency is now declarative and reconstructable.

Stack6 PREPARE always provisions the Buzz CLI from pinned source even when Buzz is not configured for use. Buzz remains optional as an integration; the executable is reconstructable platform software and is **not** a backup artifact.

Host qualification passed after rebuilding pinned Buzz commit `78618804ec86a014524ad7d1fb55928e8f5c3edf` with `cargo build --locked --release -p buzz-cli`. The resulting 17,516,960-byte executable was installed at `/opt/docker/runtime/service_-_hermes/data/bin/buzz` with mode `0755`, owner `10000:10000`, and executed successfully inside Hermes via `/opt/data/bin/buzz --help`. After the operator manually restarted the Hermes gateway, the web UI reported Telegram, API server and Buzz connected.
