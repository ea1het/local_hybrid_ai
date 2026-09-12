# Architecture Decision Records

ADRs preserve architectural choices that are expensive to rediscover from implementation alone.

| ADR | Status | Decision |
|---|---|---|
| [0001](0001-backup-operational-env.md) | Accepted | Carry protected operational configuration in complete DR recovery points |
| [0002](0002-single-management-cli.md) | Accepted | `local-ai` is the sole supported management interface and anticorruption boundary |

Security rationale belongs in `sdr/`. A decision may reference both an ADR and an SDR when architecture and threat treatment overlap.
