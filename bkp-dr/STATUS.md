# DR Status and AI Handoff

Updated after the successful destructive clean-target `restore all` qualification and Stack6 Buzz reconstruction qualification on 2026-09-12.

## Purpose

This is the continuity document for the next AI/coding agent. Read it together with [`README.md`](README.md), [`dr-howto.md`](dr-howto.md), [`../a2aknowledge.md`](../a2aknowledge.md), [`../pending.md`](../pending.md), [`../ADRs/`](../ADRs/), the affected stack manifest/README and current Git history before changing anything.

## Architecture decisions already made

1. Recovery policy is manifest-driven. Do not discover every persistent mount and assume it must be backed up.
2. Source is Git at a known commit/tag. Operational mutable state is outside the checkout under `/opt/docker/runtime`.
3. ADR-0001 accepts including the protected root operational `.env` directly in each complete DR backup set until a better secret-recovery mechanism exists. It is a global sensitive artifact, not a stack-owned resource. Never print it or commit it.
4. Stack0 PKI/private identity is preserved so a rebuilt platform retains the same trust identity.
5. Stack2 Firecrawl/SearXNG data is reconstructable; no Firecrawl PostgreSQL/Redis/RabbitMQ/SearXNG backup is required.
6. Stack3 preserves the LiteLLM logical PostgreSQL database. `LITELLM_SALT_KEY` is carried by the protected `.env` artifact in complete backup sets. PostgreSQL admin credentials may be regenerated on a clean rebuild.
7. Stack4 preserves Gitea repositories and durable application state with Gitea's native dump. Gitea uses SQLite plus filesystem/repositories, not PostgreSQL.
8. Stack5 Dockhand is reconstructable; its Docker volume is not a DR target.
9. Stack6/Hermes is replaceable and reconstructable as a whole. The only current durable application-level exception is user-owned portable memory: Git-backed `MEMORY.md` + `USER.md`.
10. Stack6's Git remote is configuration, not a required Stack4 dependency. It may be Gitea, another Git SaaS/service, or another configured repository.
11. `SOUL.md` is Hermes/Nous Research runtime behavior text, not operator-owned durable data. It is disposable together with Hermes SQLite databases, caches, packages, sessions, logs and the complete sandbox runtime.
12. Reconstructable executables required by a stack belong in PREPARE/build automation, not DR backup artifacts. Stack6 Buzz CLI follows this rule.
13. Do not back up raw PostgreSQL PGDATA, containers, images, logs, temp files, `.lock`, migration markers, queues or caches merely because they exist.

## Backup all — qualified

`backup all` is a real atomic recovery-set operation. It is manifest/lifecycle driven, includes the protected operational `.env`, Stack0 PKI, Stack3 LiteLLM logical PostgreSQL dump and Stack4 controlled-offline Gitea native dump, and verifies Stack6 external Git prerequisites.

Historical canonical qualification set remains:

```text
/opt/local-hybrid-ai-backups/backup-20260911T004927Z
```

A fresh pre-wipe recovery point was subsequently created and used for the destructive clean-target recovery proof:

```text
/opt/local-hybrid-ai-backups/backup-20260911T172551Z
source_commit = 7cbfa2874f6e865a4de6e2854b2589de52a39913
```

That fresh set contained all seven deployed stacks in the resolved closure, four recovery artifacts, two external/required prerequisites, and passed its checksum index before and after recovery.

## Restore all — destructive clean-target qualification PASS

The reference host was intentionally used as an explicitly operator-authorized destructive DR target. The test stopped and removed the platform containers, removed reconstructable platform Docker objects, destroyed `/opt/docker`, retained the backup repository and recovery tooling outside the target, and rebuilt the platform from the fresh recovery point.

The clean-target preflight passed with `/opt/docker` absent. During first execution the real test exposed three recovery-tooling defects/compatibility issues rather than backup corruption:

- global artifact lookup used historical `id` instead of schema field `resource_id`;
- restored-source comparison passed `git show` bytes through `.strip()`, causing a false source mismatch;
- the historical Stack6 lifecycle could validate immediately after reconcile while Hermes was still `running/starting` after recreation.

The tooling was corrected/fail-closed and a bounded resume was used; the host was **not wiped again** and managed databases were not blindly re-imported. Final bounded resume reported:

```text
RESTORE ALL RESUME: PASS
source commit: 7cbfa2874f6e865a4de6e2854b2589de52a39913
resolved stacks: 0,1,2,3,4,5,6
LiteLLM PostgreSQL tables: 75
Gitea SQLite tables: 116
Gitea repositories: 8
portable memory HEAD: e9c220aa26b29303a18fa4b3f43f1c6edc0760ca
Stack6 memory-sync profile: running
```

All expected containers were then running and healthchecks were healthy where defined: HAProxy/web, Stack2 services, LiteLLM/PostgreSQL, Gitea/runner, Dockhand, Hermes/sandbox/cleanup and `hermes-memory-sync`. The recovery point checksum index still passed. The restored `install.py` byte-for-byte SHA matched the recorded source commit.

This is the definitive proof that current `backup all` + clean-target recovery can reconstruct the declared platform and its durable state from a real recovery point. Remaining DR work is operational hardening (encryption/off-host/retention, locking/type hardening, etc.), not an unproven core backup/restore path.

## Stack6 persistence and external prerequisites

Hermes and sandbox runtime are replaceable. Portable durable memory remains deliberately narrow:

```text
MEMORY.md   durable / Git-backed
USER.md     durable / Git-backed
```

The Stack6 Git remote is externalized configuration. `dr_stack6_verify.py` verifies origin/branch, required tracked regular files, clean working tree and local HEAD alignment without mutating Git.

The memory-sync SSH identity is an operator-provisioned external prerequisite under `${BASE_PATH}/service_-_hermes-memory-sync/ssh`; it is not silently generated by Hermes maintenance and is not promoted to application data. The destructive restore proof explicitly preserved/reprovisioned this external credential and successfully returned the `git-memory` profile to running state.

## Stack6 Buzz CLI — reconstructable and host-qualified

Buzz was historically compiled manually from GitHub and copied to `/opt/docker/runtime/service_-_hermes/data/bin/buzz`. The destructive wipe correctly removed it and exposed that this executable dependency was not declaratively reconstructable.

Stack6 now owns automatic Buzz provisioning. Buzz remains optional as a configured Hermes integration, but the CLI binary is always pre-provisioned during Stack6 PREPARE so enabling Buzz never depends on historical runtime accumulation. The implementation builds a pinned Buzz source commit in a disposable Docker builder and installs only the resulting executable into the Hermes runtime. The binary is not a DR backup artifact.

Host qualification PASS evidence:

- pinned source commit `78618804ec86a014524ad7d1fb55928e8f5c3edf`;
- Docker builder completed `cargo build --locked --release -p buzz-cli`;
- installed path `/opt/docker/runtime/service_-_hermes/data/bin/buzz`;
- installed size `17516960` bytes, mode `0755`, owner `10000:10000`;
- `docker exec hermes /opt/data/bin/buzz --help` PASS;
- Hermes UI showed Telegram, API server and Buzz connected after the operator performed a manual gateway restart.

Future clean deployments/recoveries must obtain Buzz through Stack6 PREPARE/build automation, never by backing up or manually restoring the runtime binary.

## Installer lesson from destructive recovery

A lifecycle RECONCILE that restarts/recreates required services must be followed by READY convergence before final VERIFY. The historical source commit used by the recovery point could observe Hermes as `running/starting` immediately after reconcile. Recovery compatibility handled that historical behavior narrowly; the current installer should preserve the stronger lifecycle rule so future recovery points do not depend on a compatibility shim.

`.lock` continues to mean PREPARED only, never deployed/healthy/ready.

## Operator shell safety

Commands pasted into the operator's interactive shell must not use global `set -e`, `set -Eeuo pipefail`, `exit` or `exec`. Capture return codes and branch explicitly. Avoid broad cleanup. End operator blocks with `echo "La shell permanece abierta."`.

## Known cleanup boundary

The operator owns deletion of rollback material under `/root`; do not delete it or provide automatic `/root` cleanup. Backup sets under `/opt/local-hybrid-ai-backups` are recovery evidence and are not test debris unless the operator explicitly reclassifies them. Everything under `/opt/docker/runtime/service_-_hermes-sandbox` is disposable for DR purposes, but broad runtime deletion is not routine cleanup.

## Next-agent boundary

Do not repeat the destructive wipe merely to prove the already-qualified core path. Preserve the recovery evidence and current recovered platform. Next work should: (1) keep the Stack6 Buzz provisioning contract regression-tested, (2) ensure current installer readiness semantics wait after restart-causing reconcile, (3) update operational DR documentation around the external memory-sync SSH prerequisite and bounded resume behavior, and (4) proceed to remaining P1 hardening or the planned independent Open WebUI stack once documentation/regressions are clean.
