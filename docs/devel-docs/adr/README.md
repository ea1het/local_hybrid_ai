# Architecture Decision Records

[Documentation TOC](../../TOC.md) · [Developer documentation](../README.md) · [Security decisions](../sdr/README.md) · [OpenSpec](../openspec/README.md)

ADRs preserve architectural choices that are expensive to rediscover from implementation alone. They explain *why* the platform has a particular shape; manifests, stack README files and OpenSpec show how that decision appears in the current implementation and observable behaviour.

| ADR | Status | Decision |
|---|---|---|
| [0001](0001-backup-operational-env.md) | Accepted | Carry protected operational configuration in complete DR recovery points |
| [0002](0002-single-management-cli.md) | Accepted | `local-ai` is the sole supported management interface and anticorruption boundary |
| [0003](0003-human-version-vs-image-digest.md) | Accepted | Discover container versions from the configured image registry while retaining immutable digest identity |
| [0004](0004-upgrade-compatibility-policy.md) | Accepted | Separate registry availability from installation-owned upgrade compatibility policy |
| [0005](0005-unified-command-implementation-package.md) | Accepted | Organize all private management implementation under `commands/`, with recovery as a cohesive subpackage |

Security rationale belongs in the sibling [SDR index](../sdr/README.md). A decision may reference both an ADR and an SDR when architecture and threat treatment overlap. Cross-stack impact should also be visible from the [stack map](../../stacks/README.md) and, where observable behaviour changes, from [OpenSpec traceability](../openspec/traceability.md).
