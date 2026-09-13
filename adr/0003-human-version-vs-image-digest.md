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
   When a digest can be associated with a human version tag in the package, that tag is the operator-facing current version. A digest-only deployment such as `ghcr.io/firecrawl/firecrawl@sha256:...` may therefore display a human tag once the registry proves that mapping.

3. **Digests remain authoritative machine identity.**
   The exact local and remote digests remain in structured JSON and continue to be used for immutable comparison, drift evidence and recovery/rollback decisions.

4. **Tag and digest are different facts.**
   Tags are mutable names. Digests identify immutable artifacts. `local-ai` preserves both rather than treating a digest as a human version.

5. **A published human version must be registry-evidenced.**
   `local-ai` never infers that a digest corresponds to a source-code release merely because the numbers look related. A human version is shown only when the image registry exposes that tag for the same package/artifact.

6. **Channels remain channels.**
   Tags such as `latest`, `alpine`, `3-alpine` or `3.0-alpine` may represent moving channels. When possible, `local-ai` resolves the digest behind the channel and maps it to a more specific human version tag in the same package.

7. **Discovery stays in the configured version family.**
   Human candidates preserve meaningful tag conventions from the configured image: `v` prefixes, image variants such as `alpine` or `rootless`, and the configured major series. Numeric channel tags such as `3-alpine` and `3.0-alpine` stay inside the corresponding numeric prefix. Build hashes are treated as build identities rather than reusable variants. This prevents unrelated tags such as hotfix branches, another major line, or another channel from being advertised as the next version.

8. **Discovery is monotonic for explicit release tags.**
   When the configured image already names a concrete human release, a candidate numerically older than that deployed release is never advertised as `AVAILABLE`. If registry pagination or retention exposes only older tags, `local-ai` falls back to the deployed release as current rather than presenting a downgrade as an update.

9. **Registry tag lists are paginated.**
   Discovery follows Registry V2 pagination for the same package. It must not decide that an older-looking tag is latest merely because it appeared on the first registry page.

10. **Digest-only deployments may require tag-to-digest resolution.**
   `local-ai` first uses trustworthy local image metadata when it names a tag published by the same package. Otherwise it compares candidate registry tags with the deployed digest. This lookup is bounded and fail-closed: failure to prove a mapping leaves the current human version unknown rather than inventing one.

11. **Discovery is not upgrade authorization.**
    A newer registry tag is only a discovered candidate. The separate support/compatibility layer decides which targets are valid to select or execute. `upgrade --yes` still applies only explicitly selected and executable components.

12. **Registry failures preserve their reason.**
    Rate limiting, authorization failures and similar lookup errors remain `available=unknown` with structured statuses such as `rate_limited`. A failure to inspect a registry must never be rendered as `current`.

13. **Local-only images are exempt.**
    Images such as the Hermes sandbox that intentionally exist only in the local installation remain `local` and are never queried against an external registry.

## Consequences

- Container discovery has one source of truth per component: the registry named by its image.
- Existing digest pins remain valid and desirable for reproducibility.
- Operator output can use readable published versions while JSON preserves exact artifact identity.
- GitHub Releases are no longer an operational version source for container inventory merely because the source project is hosted on GitHub.
- GHCR packages are queried as GHCR packages, Docker Hub images as Docker Hub packages, and other registries through their own Registry V2 interface.
- Registry pagination, tag-family filtering and monotonic candidate selection are part of correctness, not presentation polish.
- A registry tag discovered as newer is not automatically supported, selected or applied.
- Compatibility/version-policy work remains a separate layer above discovery.
