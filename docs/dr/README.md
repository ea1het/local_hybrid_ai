<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Disaster recovery

[← Documentation map](../TOC.md)

Disaster recovery is manifest-driven and exposed only through the supported `./local-ai` management boundary. Recovery distinguishes state that must be backed up from state that is reconstructable from declarative source.

## Operator path

1. [How to operate backup and restore](howto.md)
2. [Current qualification status](status.md)
3. Use the resource-specific design documents below when diagnosing or extending recovery behaviour.

## Resource strategies

- [Filesystem resources](filesystem.md)
- [Archive resources](archive.md)
- [PostgreSQL resources](postgres.md)
- [Gitea](gitea.md)

## Related decisions and contracts

- [ADR-0001 — protected operational `.env` in backups](../devel-docs/adr/0001-backup-operational-env.md)
- [SDR-0001 — security treatment of protected operational configuration](../devel-docs/sdr/0001-protected-operational-config-in-backups.md)
- [Disaster-recovery OpenSpec](../devel-docs/openspec/disaster-recovery.feature)
- [OpenSpec traceability](../devel-docs/openspec/traceability.md)

A backup set is not considered valid merely because files exist. Publication is atomic and restore paths validate the recovery contract and integrity evidence before mutation.
