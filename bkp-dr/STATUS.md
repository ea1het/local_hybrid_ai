# DR Status and AI Handoff

Updated after the successful Stack4 consistent-backup/isolated-restore validation, the generic execution-context end-to-end qualification, the final full-suite synchronization/cleanup PASS, and the Stack6 replaceability decision on 2026-09-11.

## Purpose

This file is the continuity document for the next AI/coding agent. Read it together with [`README.md`](README.md), [`dr-howto.md`](dr-howto.md), [`../a2aknowledge.md`](../a2aknowledge.md), [`../pending.md`](../pending.md), the affected stack manifest/README and current Git history before changing anything.

## Architecture decisions already made

1. Recovery policy is manifest-driven. Do not discover every persistent mount and assume it must be backed up.
2. Source is Git at a known commit/tag. Operational mutable state is outside the checkout under `/opt/docker/runtime`.
3. A protected operational `.env` is a global DR prerequisite. Never print it or commit it.
4. Stack0 PKI/private identity is preserved so a rebuilt platform retains the same trust identity.
5. Stack2 Firecrawl/SearXNG data is reconstructable; no Firecrawl PostgreSQL/Redis/RabbitMQ/SearXNG backup is required.
6. Stack3 preserves the LiteLLM logical PostgreSQL database plus the original `LITELLM_SALT_KEY`. PostgreSQL admin credentials may be regenerated on a clean rebuild.
7. Stack4 preserves Gitea repositories and durable application state with Gitea's native dump. Definitive consistency policy is a brief controlled stop of only Gitea, native dump using the execution context discovered from the deployed container, restart + health verification, then artifact validation/publication. Rootless vs. rootful is not part of the DR contract.
8. Stack5 Dockhand is reconstructable; its Docker volume is not a DR target.
9. Stack6/Hermes is replaceable and reconstructable as a whole. The only current durable application-level exception is user-owned portable memory: Git-backed `MEMORY.md` + `USER.md`.
10. `SOUL.md` is Hermes/Nous Research runtime behavior text, not operator-owned durable data. It is disposable together with Hermes SQLite databases, caches, packages, sessions, logs and the complete sandbox runtime.
11. Do not back up raw PostgreSQL PGDATA, containers, images, logs, temp files, `.lock`, migration markers, queues or caches merely because they exist.

## Stack4 execution-context rule

The Stack4 adapter must not assume a historical Gitea layout. Before stopping the live service it discovers image, configured container user when present, work path, `GITEA_CUSTOM`, and the active `app.ini` path from deployment evidence. The helper uses the same image and mounted volumes. If no explicit container user is configured, `--user` is omitted so the image keeps its default identity. `gitea` is invoked through image `PATH`; no rootless-specific binary path is hard-coded. Config discovery fails closed before downtime if the active `app.ini` cannot be identified.

Synthetic unit coverage models both rootless-style and rootful-style deployments. The current real deployment is rootless and its discovered context was `docker.gitea.com/gitea:1.27.1-rootless`, user `1000:1000`, work path `/var/lib/gitea`, custom path `/etc/gitea`, config `/etc/gitea/app.ini`. The generic-context implementation subsequently passed a fresh real controlled-offline backup and isolated restore end-to-end regression. Therefore rootless is deployment evidence, not the recovery contract. After a future image/layout/rootless-rootful transition, qualify that new deployment again with a real backup + isolated restore.

## Stack6 persistence rule

Do not promote Hermes-generated state to DR merely because it appears under persistent runtime storage. The portable boundary is deliberately narrow:

```text
MEMORY.md   durable / Git-backed
USER.md     durable / Git-backed
```

Everything else produced by Hermes is reconstructable/disposable unless the platform makes a future explicit decision to promote it. In particular, `SOUL.md`, Hermes SQLite databases and the entire `service_-_hermes-sandbox` tree are not recovery targets.

The Stack6 manifest keeps `hermes-knowledge` as an externalized Git resource for compatibility, now with `GITMEM_REPOSITORY` explicitly declared as its source. [`dr_stack6_verify.py`](dr_stack6_verify.py) is the read-only qualification tool: it verifies configured origin/branch, tracked regular `MEMORY.md` + `USER.md`, a clean working tree and local HEAD equal to the existing `origin/<branch>` tracking ref. It does not fetch, pull, commit, push or modify runtime. Host qualification of this new verifier is the only remaining Stack6-specific DR check.

## Verified real evidence

### Stack0

Real set: `/opt/local-hybrid-ai-backups/backup-20260910T162652Z`.

`platform-pki.tar` SHA-256: `5e1b3156281c061678f9f4c607958e45760e7b031823edb408e40b71c6df5597`, 20480 bytes. Isolated extraction/fingerprint verification passed without modifying source PKI.

### Stack3

Dependency-complete real set: `/opt/local-hybrid-ai-backups/backup-20260910T215453Z`.

PKI plus LiteLLM custom dump. LiteLLM dump SHA-256: `b1d2f6d804daeec2e44a7ca5d5515698de5a44b97b32b30135173e4651ac9cb1`, 299304 bytes. Temporary restore DB verification passed: 408 catalog entries, 75/75 tables, 25 non-empty tables; temporary DB removed; live DB untouched.

### Stack4

An earlier online native dump exists at `/opt/local-hybrid-ai-backups/backup-20260910T220115Z`; it is historical validation evidence, not the definitive consistency model.

First definitive controlled-offline set: `/opt/local-hybrid-ai-backups/backup-20260910T224812Z`.

- controlled-offline mode;
- Gitea stopped briefly and restarted successfully;
- Gitea healthy before and after;
- no helper container remained;
- PKI SHA-256 unchanged: `5e1b3156281c061678f9f4c607958e45760e7b031823edb408e40b71c6df5597`;
- Gitea ZIP SHA-256: `a1722839b8ea4c7258804bdd03576f31306c7ebb0ae3f7751a1fb644322a521f`;
- Gitea ZIP size: 467179130 bytes; 586 members;
- backup-set checksums passed;
- isolated restore imported 116 SQLite tables, 38 non-empty;
- 8 repositories discovered and 8/8 passed `git fsck --full --no-dangling`;
- restore temporary tree removed;
- restore verifier did not restart or modify live Gitea.

After removing rootless-specific assumptions, the operator ran the new execution-context preflight and then a fresh real generic-context controlled-offline backup + checksum validation + isolated restore verification; the complete end-to-end regression passed. The exact second backup-set path/hash was not captured in conversation, so do not invent it.

## Final synchronization / validation / cleanup state

The previous post-reorganization host validation completed with PASS: manifests validated, installer/recovery tests passed, the complete DR suite passed, `install.py all --dry-run` converged, critical services remained healthy, generated test debris was cleaned, no Gitea dump helper remained and Git was clean/synchronized at that time. Later Stack6 verifier/documentation commits still require a new host fast-forward and focused validation.

## What remains before generic DR completion

Stack6 no longer has a data-externalization gap. Remaining work is platform/engine work: qualify the new Stack6 verifier on the host; decide protected `.env` backup; encryption/retention/off-host policy; harden destination/source overlap and manifest type validation; harden the older archive publication path; integrate generic real `backup all`; then perform a clean-environment full rebuild/restore proof. See [`../pending.md`](../pending.md).

Do not destroy the current host to test recovery. Use an isolated temporary environment until the operator explicitly authorizes destructive rebuild testing.

## Operator shell safety

Commands pasted into the operator's interactive shell must not use global `set -e`, `set -Eeuo pipefail`, `exit` or `exec`. Capture return codes and branch explicitly. Avoid broad cleanup. End operator blocks with `echo "La shell permanece abierta."`.

## Known cleanup boundary

The operator owns deletion of rollback material under `/root`; do not delete it or provide automatic `/root` cleanup. Backup sets under `/opt/local-hybrid-ai-backups` are recovery evidence and are not test debris unless the operator explicitly reclassifies them.
