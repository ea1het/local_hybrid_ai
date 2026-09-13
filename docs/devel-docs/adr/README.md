# Architecture Decision Records

ADRs preserve architectural choices that are expensive to rediscover from implementation alone.

| ADR | Status | Decision |
|---|---|---|
| [0001](0001-backup-operational-env.md) | Accepted | Carry protected operational configuration in complete DR recovery points |
| [0002](0002-single-management-cli.md) | Accepted | `local-ai` is the sole supported management interface and anticorruption boundary |
| [0003](0003-human-version-vs-image-digest.md) | Accepted | Discover container versions from the configured image registry while retaining immutable digest identity |
| [0004](0004-upgrade-compatibility-policy.md) | Accepted | Separate registry availability from installation-owned upgrade compatibility policy |

Security rationale belongs in the sibling [`sdr/`](../sdr/) directory. A decision may reference both an ADR and an SDR when architecture and threat treatment overlap.
