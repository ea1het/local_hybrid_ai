# ADR-0003: Human container versions come from the image registry; digests remain immutable identity

Status: Accepted

Date: 2026-09-13

## Context

The project originally used container digests as version-like identifiers because they are immutable and make deployments reproducible. That remains correct for machine identity, rollback evidence and drift detection, but a SHA-256 digest is a poor operator-facing version.

The earlier discovery prototype also mixed sources: some components used GitHub Releases while others used their container registry. That creates avoidable ambiguity because a source-code release and a published container artifact are not necessarily the same release object and their naming/version cadence can differ.

The configured image reference already identifies the authoritative artifact source. Examples include Docker Hub, GHCR and `docker.gitea.com`. Those registries expose immutable digests and published tags for the same package.

## Decision

`local-ai` uses the registry that owns the configured container image as the sole operational source for container version discovery.

1. **Follow the configured image to its registry.**
   The registry host and repository are derived from the actual image reference. `local-ai` does not consult a separate GitHub Release feed, source repository release page or unrelated registry to decide container versions.

2. **Human display uses tags published for that exact registry package.**
   When a digest can be associated with a human version tag in the package, that tag is the operator-facing current version. A digest-only deployment such as `ghcr.io/firecrawl/firecrawl@sha256:...` may therefore display a human tag such as `2.11.300` once the registry proves that mapping.

3. **Digests remain authoritative machine identity.**
   The exact local and remote digests remain in structured JSON and continue to be used for immutable comparison, drift evidence and recovery/rollback decisions.

4. **Tag and digest are different facts.**
   Tags are mutable names. Digests identify immutable artifacts. `local-ai` preserves both rather than treating a digest as a human version.

5. **A published human version must be registry-evidenced.**
   `local-ai` never infers that a digest corresponds to a source-code release merely because the numbers look related. A human version is shown only when the image registry exposes that tag for the same package/artifact.

6. **Channels remain channels.**
   Tags such as `latest`, `alpine`, `3-alpine` or `3.0-alpine` may represent moving channels. When possible, `local-ai` resolves the digest behind the channel and maps it to a more specific human version tag in the same package.

7. **Exact version tags can discover newer tags in the same package.**
   For images already configured with a human version tag, the current version comes directly from that tag and newer published human version tags are discovered from the same registry package. Discovery does not imply compatibility or permission to upgrade.

8. **No automatic major-version policy is introduced here.**
   Registry discovery reports what the package publishes. A separate support/compatibility layer decides which discovered versions are valid upgrade targets. `upgrade --yes` still applies only explicitly selected and executable components.

9. **Registry failures preserve their reason.**
   Rate limiting, authorization failures and similar lookup errors remain `available=unknown` with structured statuses such as `rate_limited`. A failure to inspect a registry must never be rendered as `current`.

10. **Local-only images are exempt.**
    Images such as the Hermes sandbox that intentionally exist only in the local installation remain `local` and are never queried against an external registry.

## Consequences

- Container discovery has one source of truth per component: the registry named by its image.
- Existing digest pins remain valid and desirable for reproducibility.
- Operator output can use readable published versions while JSON preserves exact artifact identity.
- GitHub Releases are no longer an operational version source for container inventory merely because the source project is hosted on GitHub.
- GHCR packages are queried as GHCR packages, Docker Hub images as Docker Hub packages, and other registries through their own Registry V2 interface.
- A registry tag discovered as newer is not automatically supported, selected or applied.
- Compatibility/version-policy work remains a separate layer above discovery.
