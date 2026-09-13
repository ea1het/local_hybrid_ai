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
   The exact local and remote digests remain machine evidence for immutable comparison, drift evidence and recovery/rollback decisions.

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

11. **Latest-only packages use a readable digest identity.**
    Some packages publish no semantic/version tag and expose only `latest` plus architecture/build tags. For those packages, `local-ai` renders the immutable identity as `latest(<sha9>)`, where `<sha9>` is the first nine hexadecimal characters of the manifest digest. Example: `sha256:df1a393ce8...` becomes `latest(df1a393ce)`. This is a display identity, not a claim that `latest` is immutable.

12. **A changed `latest` digest must be proven newer before it is advertised as an update.**
    A different digest alone is not sufficient to claim that the registry's current `latest` is newer than the installed pin. `local-ai` compares registry-native timing evidence for both manifests. Registry V2 does not define a universal publication-time field, so the preferred evidence is the registry HTTP `Last-Modified` value when available; OCI `org.opencontainers.image.created` or image config `created` metadata is used as a conservative fallback. If both timestamps establish that the remote `latest` is newer, `AVAILABLE` becomes `latest(<new-sha9>)`. If the remote artifact is older, `AVAILABLE=current`. If ordering cannot be established, discovery fails closed instead of treating a different digest as a newer release.

13. **Equal latest-only digests are current without date lookup.**
    If the deployed digest and the digest currently behind `latest` are identical, the component is current regardless of timestamps. The table still renders the installed artifact as `latest(<sha9>)` so the operator can identify exactly which artifact is running.

14. **Normal upgrade discovery remains credential-free.**
    `upgrade check` must not require a GitHub token, registry-management token, or package-service credential merely to determine whether public container artifacts have changed. Where a registry exposes richer package metadata only through an authenticated management API, that API is not part of the normal discovery path. In particular, an authenticated package API may expose `created_at`/`updated_at`, but `local-ai` does not introduce a new secret dependency solely to obtain those timestamps. If public Registry V2 and OCI artifact metadata cannot establish ordering for two different latest-only digests, the result remains unknown/fail-closed.

15. **Discovery is not upgrade authorization.**
    A newer registry tag or changed channel digest is only discovered state. The separate support/compatibility layer decides which targets are valid to select or execute. `upgrade --yes` still applies only explicitly selected and executable components.

16. **Registry failures preserve their reason.**
    Rate limiting, authorization failures and similar lookup errors remain `available=unknown` with structured statuses such as `rate_limited`. A failure to inspect a registry must never be rendered as `current`.

17. **Local-only images are exempt.**
    Images such as the Hermes sandbox that intentionally exist only in the local installation remain `local` and are never queried against an external registry.

## Consequences

- Container discovery has one source of truth per component: the registry named by its image.
- Existing digest pins remain valid and desirable for reproducibility.
- Operator output uses readable published versions when they exist and `latest(<sha9>)` for latest-only packages.
- GitHub Releases are not an operational version source for container inventory merely because the source project is hosted on GitHub.
- GHCR packages are queried as GHCR packages, Docker Hub images as Docker Hub packages, and other registries through their own Registry V2 interface.
- Registry pagination, tag-family filtering, monotonic candidate selection and publication-order validation are part of correctness, not presentation polish.
- A latest-only package does not become `update` solely because its moving tag points to another digest; the newer ordering must be established from registry/artifact timing evidence.
- Normal `upgrade check` remains usable without adding service-specific package API credentials.
- A registry tag discovered as newer is not automatically supported, selected or applied.
- Compatibility/version-policy work remains a separate layer above discovery.
