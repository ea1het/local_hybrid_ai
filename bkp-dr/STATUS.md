# DR Status and AI Handoff

Updated after the successful real atomic `backup all`, stored-artifact recovery qualification, generic read-only `restore all` planner host qualification, and implementation of isolated filesystem restore staging on 2026-09-11.

## Purpose

This is the continuity document for the next AI/coding agent. Read it together with [`README.md`](README.md), [`dr-howto.md`](dr-howto.md), [`../a2aknowledge.md`](../a2aknowledge.md), [`../pending.md`](../pending.md), [`../ADRs/`](../ADRs/), the affected stack manifest/README and current Git history before changing anything.

## Architecture decisions already made

1. Recovery policy is manifest-driven. Do not discover every persistent mount and assume it must be backed up.
2. Source is Git at a known commit/tag. Operational mutable state is outside the checkout under `/opt/docker/runtime`.
3. ADR-0001 accepts including the protected root operational `.env` directly in each complete DR backup set until a better secret-recovery mechanism exists. It is a global sensitive artifact, not a stack-owned resource. Never print it or commit it.
4. Stack0 PKI/private identity is preserved so a rebuilt platform retains the same trust identity.
5. Stack2 Firecrawl/SearXNG data is reconstructable; no Firecrawl PostgreSQL/Redis/RabbitMQ/SearXNG backup is required.
6. Stack3 preserves the LiteLLM logical PostgreSQL database. `LITELLM_SALT_KEY` is carried by the protected `.env` artifact in complete backup sets. PostgreSQL admin credentials may be regenerated on a clean rebuild.
7. Stack4 preserves Gitea repositories and durable application state with Gitea's native dump. Definitive consistency policy is a brief controlled stop of only Gitea, native dump using the execution context discovered from the deployed container, restart + health verification, then artifact validation/publication. Rootless vs. rootful is not part of the DR contract.
8. Stack5 Dockhand is reconstructable; its Docker volume is not a DR target.
9. Stack6/Hermes is replaceable and reconstructable as a whole. The only current durable application-level exception is user-owned portable memory: Git-backed `MEMORY.md` + `USER.md`.
10. Stack6's Git remote is configuration, not a required Stack4 dependency. It may be Gitea, another Git SaaS/service, or another configured repository. DR must verify the configured externalized source, not assume where it is hosted.
11. `SOUL.md` is Hermes/Nous Research runtime behavior text, not operator-owned durable data. It is disposable together with Hermes SQLite databases, caches, packages, sessions, logs and the complete sandbox runtime.
12. Do not back up raw PostgreSQL PGDATA, containers, images, logs, temp files, `.lock`, migration markers, queues or caches merely because they exist.

## Generic full-backup rule

`backup all` is a real atomic recovery-set operation. Deployment discovery uses the common installer lifecycle's `required_containers`, after validating that those containers are owned by each stack manifest. Stack0 is always included. For other stacks, the presence of any required container marks the stack as deployed; partially stopped/broken deployments are therefore not silently omitted and will fail normal runtime/source preflight if they cannot be backed up safely.

The resolved deployed-stack dependency closure is processed from manifest recovery policy. Current executing strategies are `archive`, `postgres-custom-dump` and `gitea-native-dump`; externalized resources remain prerequisites rather than becoming arbitrary backup artifacts. All artifacts plus the global `.env` are created inside one private temporary backup-set directory. Metadata/checksums and fallible integrity checks complete before terminal no-replace atomic publication. A failed operation must not publish a final `backup-*` directory.

## Stack4 execution-context rule

The Stack4 adapter must not assume a historical Gitea layout. Before stopping the live service it discovers image, configured container user when present, work path, `GITEA_CUSTOM`, and the active `app.ini` path from deployment evidence. The helper uses the same image and mounted Gitea volumes. If no explicit container user is configured, `--user` is omitted so the image keeps its default identity. `gitea` is invoked through image `PATH`; no rootless-specific binary path is hard-coded. Config discovery fails closed before downtime if the active `app.ini` cannot be identified.

Synthetic unit coverage models both rootless-style and rootful-style deployments. The current real deployment is rootless and its discovered context was `docker.gitea.com/gitea:1.27.1-rootless`, user `1000:1000`, work path `/var/lib/gitea`, custom path `/etc/gitea`, config `/etc/gitea/app.ini`. The generic-context implementation passed a fresh real controlled-offline backup and isolated restore end-to-end regression. Rootless is deployment evidence, not the recovery contract.

## Stack6 persistence rule

Do not promote Hermes-generated state to DR merely because it appears under persistent runtime storage. The portable boundary is deliberately narrow:

```text
MEMORY.md   durable / Git-backed
USER.md     durable / Git-backed
```

Everything else produced by Hermes is reconstructable/disposable unless the platform makes a future explicit decision to promote it. In particular, `SOUL.md`, Hermes SQLite databases and the entire `service_-_hermes-sandbox` tree are not recovery targets.

The Stack6 manifest declares portable memory as an externalized Git resource with `GITMEM_REPOSITORY` as its configured source. [`dr_stack6_verify.py`](dr_stack6_verify.py) is read-only: it verifies configured origin/branch, tracked regular `MEMORY.md` + `USER.md`, a clean working tree and local HEAD equal to the existing remote-tracking ref. It does not fetch, pull, commit, push or modify runtime.

Reference-host qualification passed at source commit `21178fc8c71588d18252948ee3ecdea13bf718cc`; the real verifier reported branch `main`, HEAD `e9c220aa26b29303a18fa4b3f43f1c6edc0760ca`, required files `MEMORY.md` + `USER.md`, and no Hermes/sandbox/SOUL state requirement. Stack6 has no remaining data-backup gap.

## Verified real evidence

### Historical focused sets

- Stack0 real set: `/opt/local-hybrid-ai-backups/backup-20260910T162652Z`; PKI isolated extraction/fingerprint verification passed.
- Stack3 dependency-complete set: `/opt/local-hybrid-ai-backups/backup-20260910T215453Z`; LiteLLM temporary restore verification passed.
- Stack4 online historical set: `/opt/local-hybrid-ai-backups/backup-20260910T220115Z`; not definitive consistency evidence.
- Stack4 first definitive controlled-offline set: `/opt/local-hybrid-ai-backups/backup-20260910T224812Z`; Gitea restore imported 116 SQLite tables and 8/8 repositories passed `git fsck`.
- A later generic-context Stack4 controlled-offline regression also passed; its exact set path/hash was not captured, so do not invent it.

### Fully qualified atomic backup all

Canonical qualified recovery point:

```text
/opt/local-hybrid-ai-backups/backup-20260911T004927Z
```

Backup execution source commit:

```text
f732f0e1bca533556d9a60fef5bd373b51675da2
```

Creation evidence:

- focused backup-all tests 4/4 PASS;
- planner regression 25/25 PASS;
- Stack6 verifier regression 5/5 PASS;
- global dry-run/runtime source preflight PASS;
- deployed stacks detected: 0,1,2,3,4,5,6;
- artifact count 4: global `operational.env`, Stack0 PKI, Stack3 LiteLLM DB, Stack4 Gitea native dump;
- prerequisite count 2: Stack3 protected-config declaration and Stack6 external Git declaration;
- atomic publication PASS;
- Gitea returned running/healthy;
- no dump helper remained;
- source worktree clean.

Stored-artifact recovery qualification from that exact same set subsequently passed:

- full-set compatibility tests 4/4 PASS;
- archive restore regression 6/6 PASS;
- all backup-set checksums PASS;
- Stack0 PKI: isolated extraction, 3 archive members, restored/source fingerprint match PASS, temporary cleanup PASS, live runtime untouched;
- Stack3 LiteLLM: stored dump 299321 bytes, 408 catalog entries, 75/75 source/restored tables, 25 non-empty restored tables, temporary restore DB removed, live DB untouched, container not restarted;
- Stack4 Gitea: 586 ZIP members, 116 SQLite tables, 38 non-empty tables, 8/8 repositories passed `git fsck`, temporary restore removed, live Gitea untouched/not restarted by verifier;
- global `operational.env`: backup SHA-256 exactly matched the live root `.env` at qualification time;
- Stack6 externalized memory verifier PASS on branch `main`, HEAD `e9c220aa26b29303a18fa4b3f43f1c6edc0760ca`, tracked `MEMORY.md` + `USER.md`; runtime Hermes/sandbox/SOUL not required;
- Gitea, LiteLLM PostgreSQL, LiteLLM, Hermes, sandbox and memory-sync remained running/healthy as applicable;
- Git worktree ended clean.

Therefore `backup all` is not merely creation-qualified: every currently declared recovery component in the canonical full recovery point has been independently verified from the stored artifact/prerequisite without modifying live application state.

## Full-set verifier compatibility lesson

Older focused restore verifiers assumed a single-purpose backup set. The full recovery point exposed that coupling. The archive verifier, common completed-metadata validator, PostgreSQL stored-artifact verifier and Stack4 metadata/restore path were updated so a strategy adapter locates its own resource inside a multi-resource set rather than requiring that resource to be the only content. Future `restore all` must preserve this rule: orchestration is generic; strategy adapters consume the resource selected from metadata.

## Generic restore-all planner

[`dr_restore_all.py`](dr_restore_all.py) and [`restore-all.py`](restore-all.py) implement the first inverse-path milestone. The planner is intentionally read-only and real restore execution remains blocked. It validates completed backup metadata, exact checksum-index coverage, every stored file checksum, availability of the recorded source commit, current manifest strategy/restore-phase correspondence, installer lifecycle/directory correspondence, and emits the ordered phase contract:

```text
global -> pre-prepare -> prepare -> post-prepare-pre-deploy -> deploy -> post-deploy -> external -> verify
```

The reference host has now qualified this planner against the canonical recovery point. The real dry-run resolved stacks 0-6, verified five checksummed files, placed source + `operational.env` + `litellm-salt` in global, Stack0 PKI in `pre-prepare`, Stack3 PostgreSQL + Stack4 Gitea in `post-prepare-pre-deploy`, Stack6 Git memory in `external`, and all stack lifecycle phases in order. Focused and complete DR tests passed, a no-`--dry-run` invocation failed closed with the expected blocked-execution return code, the installer remained converged, runtime stayed healthy, and Git ended clean at the qualified source revision.

## Isolated filesystem staging milestone

[`dr_restore_stage.py`](dr_restore_stage.py) and [`restore-stage.py`](restore-stage.py) implement the next bounded executing slice. They execute only phases that can be proven without touching live services: materialize the recorded Git commit into an isolated source tree, copy the protected `operational.env` into that staged source with mode `0600`, verify `REQUIRE`/`external-config` prerequisites from the staged environment without printing values, and extract `pre-prepare` archive artifacts into an isolated runtime root. The v1 archive contract restores the Stack0 `pki/` tree under the isolated platform runtime.

This staging executor does **not** run PREPARE/DEPLOY, restore PostgreSQL, restore Gitea, mutate external Git, or touch `/opt/docker/runtime`. On failure it removes only its own isolated staging destination. Focused tests are in [`tests/test_dr_restore_stage.py`](tests/test_dr_restore_stage.py). Host qualification of this staging slice against the canonical recovery point is the next step.

## Global `.env` decision

[`ADR-0001`](../ADRs/ADR-0001-backup-operational-env.md) accepts a pragmatic recovery compromise: the exact protected operational root `.env` is copied into each complete backup set as a sensitive global artifact. This removes the external-config survival gap and makes the matching recovery point carry values such as `LITELLM_SALT_KEY`.

Encryption/off-host protection may supersede the storage mechanics later without changing the logical requirement that operational configuration be restored before PREPARE.

## Next-agent boundary

The next P0 step is to qualify isolated filesystem staging on the reference host, then extend execution into a genuinely isolated clean service environment. Strategy adapters must continue to own strategy mechanics; generic orchestration must not branch on stack IDs. PostgreSQL/Gitea restore execution must target isolated services/data roots before any live-host recovery path is enabled.

Do not destroy the current reference host without explicit operator authorization.

## Operator shell safety

Commands pasted into the operator's interactive shell must not use global `set -e`, `set -Eeuo pipefail`, `exit` or `exec`. Capture return codes and branch explicitly. Avoid broad cleanup. End operator blocks with `echo "La shell permanece abierta."`.

## Known cleanup boundary

The operator owns deletion of rollback material under `/root`; do not delete it or provide automatic `/root` cleanup. Backup sets under `/opt/local-hybrid-ai-backups` are recovery evidence and are not test debris unless the operator explicitly reclassifies them. Everything under `/opt/docker/runtime/service_-_hermes-sandbox` is disposable for DR purposes, but broad runtime deletion is not part of routine qualification cleanup.
