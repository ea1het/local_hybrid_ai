# Configuration

[← Documentation map](../TOC.md)

Configuration is split deliberately between declarative source in Git and installation-owned mutable or sensitive state outside the checkout.

## Documents

- [Environment and secrets](env-secrets.md) — root `.env`, secret classes, persistence and rotation constraints.
- [Installation lifecycle](../installation.md) — how configuration is validated and consumed during PREPARE/DEPLOY.
- [ADR-0001](../devel-docs/adr/0001-backup-operational-env.md) — why protected operational configuration is part of DR.
- [SDR-0001](../devel-docs/sdr/0001-protected-operational-config-in-backups.md) — security treatment of that protected configuration.

The root `.env` is operational state, not a disposable generated file. Stack preparation must not silently replace it.
