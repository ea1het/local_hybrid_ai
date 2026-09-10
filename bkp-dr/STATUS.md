# DR Status and AI Handoff

Updated after the successful Stack4 consistent-backup and isolated-restore validation on 2026-09-11.

## Purpose

This file is the continuity document for the next AI/coding agent. Read it together with [`README.md`](README.md), [`dr-howto.md`](dr-howto.md), [`../a2aknowledge.md`](../a2aknowledge.md), [`../pending.md`](../pending.md), the affected stack manifest/README and current Git history before changing anything.

## Architecture decisions already made

1. Recovery policy is manifest-driven. Do not discover every persistent mount and assume it must be backed up.
2. Source is Git at a known commit/tag. Operational mutable state is outside the checkout under `/opt/docker/runtime`.
3. A protected operational `.env` is a global DR prerequisite. Never print it or commit it.
4. Stack0 PKI/private identity is preserved so a rebuilt platform retains the same trust identity.
5. Stack2 Firecrawl/SearXNG data is reconstructable; no Firecrawl PostgreSQL/Redis/RabbitMQ/SearXNG backup is required.
6. Stack3 preserves the LiteLLM logical PostgreSQL database plus the original `LITELLM_SALT_KEY`. PostgreSQL admin credentials may be regenerated on a clean rebuild.
7. Stack4 preserves Gitea repositories and durable application state with Gitea's native dump. Definitive consistency policy is a brief controlled stop of only Gitea, native dump using the same rootless image/context, restart + health verification, then artifact validation/publication.
8. Stack5 Dockhand is reconstructable; its Docker volume is not a DR target.
9. Stack6 Hermes runtime is intended to be reconstructable. Durable memory/identity/knowledge belongs in Git/Gitea, not arbitrary runtime backup targets.
10. Do not back up raw PostgreSQL PGDATA, containers, images, logs, temp files, `.lock`, migration markers, queues or caches merely because they exist.

## Verified real evidence

### Stack0

Real set: `/opt/local-hybrid-ai-backups/backup-20260910T162652Z`.

`platform-pki.tar` SHA-256: `5e1b3156281c061678f9f4c607958e45760e7b031823edb408e40b71c6df5597`, 20480 bytes. Isolated extraction/fingerprint verification passed without modifying source PKI.

### Stack3

Dependency-complete real set: `/opt/local-hybrid-ai-backups/backup-20260910T215453Z`.

PKI plus LiteLLM custom dump. LiteLLM dump SHA-256: `b1d2f6d804daeec2e44a7ca5d5515698de5a44b97b32b30135173e4651ac9cb1`, 299304 bytes. Temporary restore DB verification passed: 408 catalog entries, 75/75 tables, 25 non-empty tables; temporary DB removed; live DB untouched.

### Stack4

An earlier online native dump exists at `/opt/local-hybrid-ai-backups/backup-20260910T220115Z`; it is historical validation evidence, **not the definitive consistency model**.

Definitive consistent set: `/opt/local-hybrid-ai-backups/backup-20260910T224812Z`.

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

Gitea runtime is rootless: image `docker.gitea.com/gitea:1.27.1-rootless`, user `1000:1000`, workdir `/var/lib/gitea`, `GITEA_CUSTOM=/etc/gitea`. The backup helper must preserve this context.

## What remains before generic DR completion

Highest priority is Stack6/Hermes externalization. Inventory operator-valued runtime knowledge/identity, especially `SOUL.md` and anything else whose loss would matter, move authoritative copies into the intended Git/Gitea knowledge model, and make the manifest's externalized Git resource verifiable.

After that, harden generic engine edges before enabling real `dr.py backup all`: destination/source overlap rejection; manifest validator type hardening; old archive adapter publication semantics; backup encryption/retention/off-host policy; protected `.env` backup policy; generic adapter orchestration; clean-environment end-to-end restore drill.

Do not destroy the current host to test recovery. Use an isolated temporary environment until the operator explicitly authorizes destructive rebuild testing.

## Operator shell safety

Commands pasted into the operator's interactive shell must not use global `set -e`, `set -Eeuo pipefail`, `exit` or `exec`. Capture return codes and branch explicitly. Avoid broad cleanup. End operator blocks with `echo "La shell permanece abierta."`.

## Known cleanup boundary

The operator owns deletion of rollback material under `/root`; do not delete it or provide automatic `/root` cleanup. Backup sets under `/opt/local-hybrid-ai-backups` are recovery evidence and are not test debris unless the operator explicitly reclassifies them.
