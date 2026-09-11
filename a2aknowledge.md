# A2A Knowledge — Local Hybrid AI

> Continuity contract for AI/coding agents and maintainers. Read this file, [`README.md`](README.md), [`pending.md`](pending.md), and for DR work [`bkp-dr/STATUS.md`](bkp-dr/STATUS.md) before modifying the project.

## Invariants

The platform is a set of atomic stacks, not a monolithic Compose application. Git source lives under `/opt/docker/stacks`; mutable state under `/opt/docker/runtime`; the operational root `.env` is protected and ignored by Git. Stack0 owns only shared foundation. Every application stack requires Stack0; Stack6 additionally requires Stack3. Stack2 and Stack4 are optional capability providers for Stack6.

```mermaid
flowchart TB
  S0[0 Platform] --> S1[1 Ingress/Web]
  S0 --> S2[2 Search/Extract]
  S0 --> S3[3 LiteLLM/MCP]
  S0 --> S4[4 Gitea/Runner]
  S0 --> S5[5 Dockhand]
  S0 --> S6[6 Hermes]
  S3 -->|required| S6
  S2 -. optional .-> S6
  S4 -. optional .-> S6
```

Dependencies/capabilities belong in manifests. Generic installer or DR engines must not accumulate stack-number special cases when the contract can express the behavior.

## Lifecycle

PREPARE creates/validates stack-owned resources; DEPLOY establishes required processes; READY proves usability; RECONCILE adapts consumers to changed optional capabilities; VERIFY validates the result. `.lock` means PREPARED only. Running is not automatically READY.

The common installer must not rewrite `.env`, delete `.lock`, reset databases, prune Docker, run historical migration helpers or silently recreate healthy services because tracked configuration changed. Configuration/version drift detection and concurrency locking remain pending.

## Security/data ownership

PostgreSQL application stacks separate `postgres` admin/bootstrap identity from non-admin application roles. Stack2 application role is `firecrawl`; Stack3 uses the LiteLLM app role. Admin passwords are stack-owned restricted runtime secrets. Do not recursively chown/reset existing PGDATA.

Stack4/Gitea does **not** use PostgreSQL in the current architecture. It uses SQLite at `/var/lib/gitea/gitea.db` plus filesystem repositories/data. Its DR path rebuilds that SQLite database from the Gitea native dump and restores repositories/filesystem state.

Hermes has no Docker socket. Execution is via SSH to an isolated sandbox that is not attached to `redlocal`. Optional local capability absence must fail closed rather than silently use cloud.

Hermes is intentionally replaceable. The complete Hermes runtime and sandbox are reconstructable/disposable for DR, including `SOUL.md`, SQLite state, caches, packages, sessions and logs. The only current durable Stack6 application state is portable user memory: `MEMORY.md` + `USER.md`, externalized to Git. Future Hermes-generated files remain disposable unless the platform explicitly promotes them to durable state.

## DR

DR is isolated under [`bkp-dr/`](bkp-dr/README.md). Recovery policy is manifest-driven and narrower than runtime persistence. ADR-0001 currently carries the exact protected operational root `.env` inside each complete private backup set as a global sensitive artifact; never print or commit it.

Current policy: Stack0 PKI BACKUP; Stack1 RECONSTRUCT; Stack2 RECONSTRUCT; Stack3 LiteLLM PostgreSQL DB BACKUP with its salt carried by the protected `.env`; Stack4 Gitea SQLite/filesystem/repos BACKUP via native dump; Stack5 RECONSTRUCT; Stack6 RECONSTRUCT with external Git-backed `MEMORY.md` + `USER.md` as the sole durable exception. Stack6's Git remote is configuration, not a required Stack4 dependency: it may be Gitea, another Git service/SaaS, or another configured repository.

Generic real `backup all` is implemented and host-qualified. The canonical qualified set is `/opt/local-hybrid-ai-backups/backup-20260911T004927Z`, created from source commit `f732f0e1bca533556d9a60fef5bd373b51675da2`.

That exact stored set passed recovery qualification: checksums PASS; Stack0 PKI isolated fingerprint PASS; Stack3 stored PostgreSQL dump restored 75/75 tables with 25 non-empty; Stack4 stored Gitea dump restored 116 SQLite tables and 8/8 repositories passed `git fsck`; backed-up `.env` hash matched the protected file; Stack6 external Git verifier PASS; live services remained unchanged/healthy.

The generic inverse-path planner `bkp-dr/dr_restore_all.py` plus `bkp-dr/restore-all.py --dry-run` is host-qualified. Isolated filesystem staging is also host-qualified: source commit, `.env` mode `0600`, protected external-config prerequisite, and Stack0 PKI were reconstructed outside live runtime.

The managed-state slice is now host-qualified. It restored Stack3 into a disposable isolated PostgreSQL container and Stack4 into reconstructed SQLite/filesystem state, then started a disposable isolated Gitea instance successfully. Results: Stack3 75 tables / 25 non-empty; Gitea 116 SQLite tables / 38 non-empty; 8 repositories validated; Gitea health PASS. Drill containers published no ports, joined no platform network, were removed, and production container identities/health stayed unchanged.

A new orchestrator, `bkp-dr/dr_restore_drill.py` with CLI `bkp-dr/restore-drill.py`, composes planner + isolated source/env/PKI staging + managed-state reconstruction + read-only external Git prerequisite verification from a **fresh destination**. This is the next qualification step. It still does not enable live restore.

The next major boundary after that drill is lifecycle PREPARE/DEPLOY/READY/VERIFY in a genuinely isolated Docker environment. Do not use the current reference host as a destructive recovery target and do not enable production mutation before that clean-target lifecycle proof passes.

## Operator shell safety

The operator pastes command blocks into an existing interactive shell. Do not put `set -e`, `set -Eeuo pipefail`, `exit` or `exec` in pasted interactive blocks. Capture return codes and branch explicitly. Do not use broad cleanup. End blocks visibly with `echo "La shell permanece abierta."`.

## Never do casually

Do not run `docker compose down -v`, broad Docker prune, delete `/opt/docker/runtime`, overwrite `.env` from the template, print secrets, rotate persistent identities merely because they can be regenerated, reset PGDATA, give Hermes Docker socket access, attach its sandbox to `redlocal`, silently enable cloud fallback, or infer DR importance solely from a bind mount/volume/database file.

The operator owns cleanup of rollback material under `/root`; do not automate its deletion. Verified backup sets under `/opt/local-hybrid-ai-backups` are recovery evidence, not cleanup debris.

## Change procedure

Identify the owning stack; inspect manifest/Compose/scripts/runtime contract; preserve invariants; make the smallest ownership-correct change; validate source first; test the real feature/failure path; verify runtime invariants; update docs; leave Git and deployed host on the same intended commit when deployment is in scope.

For project backlog and the planned independent Open WebUI stack, use [`pending.md`](pending.md). For stack-specific behavior use each stack README linked from [`README.md`](README.md).
