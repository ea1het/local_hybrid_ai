# ADR-0001 — Include the operational `.env` in DR backup sets

- Status: Accepted
- Date: 2026-09-11
- Scope: Backup / disaster recovery

## Context

The platform uses a protected root operational `.env` outside version control as the authoritative source for deployment configuration and several secrets/identities needed to reconstruct the system. One example is `LITELLM_SALT_KEY`, whose loss can make restored LiteLLM state unusable even when the PostgreSQL logical dump itself is valid.

The previous DR model treated `.env` as an external prerequisite that the backup engine merely checked for presence. That left a recovery gap: a completed backup set was not self-contained enough to rebuild the platform unless a separately managed copy of `.env` also survived.

There are stronger long-term alternatives, such as a dedicated secrets manager, encrypted configuration bundle, hardware-backed secret storage or another independent protected recovery channel. None is currently implemented.

## Decision

A real DR backup set SHALL include an exact copy of the current operational root `.env` as a sensitive global recovery artifact.

The artifact belongs to the platform backup set, not to any individual stack manifest. Stack manifests continue to describe stack-specific recovery policy. The `.env` artifact is a global recovery input because it spans multiple stacks and the common platform lifecycle.

The backup engine MUST treat the file as secret material:

- never print its contents;
- never include secret values in `backup.json`, logs or checksums output beyond the artifact hash itself;
- preserve it only inside the private backup-set staging/publication boundary;
- require restrictive backup-root permissions;
- checksum and size-verify it like every other artifact;
- restore it before stack preparation/deployment in a clean recovery workflow;
- never commit it to Git.

Until a stronger secret-storage mechanism replaces this decision, a completed `backup all` without the `.env` artifact is not considered a complete platform recovery point.

## Stack6 independence

Stack6 portable memory is externalized through a configured Git repository, but that repository is not required to be hosted by Stack4/Gitea. It may point to Gitea, another Git SaaS/service, or be absent when Git-backed memory is not configured/used according to the Stack6 contract. No Stack6 ↔ Stack4 DR dependency is introduced by this ADR.

## Consequences

Positive consequences:

- one backup set contains the configuration/secrets required to interpret and restore its stateful artifacts;
- the LiteLLM salt and other operational values travel with the matching recovery point;
- `restore all` can have a deterministic pre-prepare source of operational configuration.

Negative consequences:

- backup sets become highly sensitive because they contain plaintext operational secrets;
- filesystem permissions, future encryption-at-rest, retention and off-host handling become more important;
- compromise of a backup set can expose credentials that were valid at backup time.

## Follow-up

The current accepted compromise is plaintext `.env` inside the private DR set. Future work SHOULD add encryption-at-rest/off-host protection without changing the logical recovery contract. A future ADR may supersede this one when a better secret-management/recovery mechanism exists.
