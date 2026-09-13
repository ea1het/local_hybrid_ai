# ADR-0003: Human versions and immutable image identity are separate concerns

Status: Accepted

Date: 2026-09-13

## Context

The project originally used container digests as version-like identifiers because they are immutable and make deployments reproducible. That remains correct for machine identity, rollback evidence and drift detection, but a SHA-256 digest is a poor operator-facing version.

Registries expose several different concepts that must not be conflated:

- a product/release version, for example `v0.11.3`;
- a registry tag or tracking channel, for example `3-alpine`, `17.10-alpine` or `latest`;
- an immutable content digest, for example `sha256:...`.

Tags are mutable. A digest is immutable. Some projects publish semantic container tags, while others publish only a moving channel such as `latest`. Therefore there is no reliable generic conversion from digest to human version.

## Decision

`local-ai` separates human-facing version information from immutable runtime identity.

1. **Human display prefers a published release/tag/channel.**
   `upgrade check` must not present a bare digest as though it were a product version when a meaningful release/tag/channel is known.

2. **Digests remain authoritative machine identity.**
   The exact local and remote digests remain in structured JSON and are used for immutable comparison, drift evidence and future recovery/rollback decisions.

3. **A tag plus digest keeps both meanings.**
   For `repo:tag@sha256:...`, `tag` is the human tracking label and the digest is the immutable deployed artifact.

4. **A pure digest pin needs explicit tracking metadata.**
   `repo@sha256:...` has no discoverable update channel by itself. If the project intentionally tracks a mutable channel such as `repo:latest`, that channel is declared explicitly in the component catalog. The CLI may then display `latest (pinned)` while comparing the deployed digest with the digest currently behind `latest`.

5. **Do not invent semantic versions.**
   If upstream publishes only `latest`, the project must not infer that a digest corresponds to a particular GitHub release unless that mapping is explicitly known and recorded.

6. **Availability and identity remain separate.**
   `current` means the deployed immutable digest equals the digest currently behind the declared tracking tag/channel. `update` means the same declared tag/channel now resolves to a different digest. `unknown` means the comparison could not be completed. `pinned` means an immutable image is installed but no tracking channel is declared.

7. **Registry failures preserve their reason.**
   Rate limiting, authorization failures and similar lookup errors remain `available=unknown` in the stable JSON contract, with a structured registry status such as `rate_limited`. Human output may render this as `unknown (rate limited)`.

## Consequences

- Existing digest pins remain valid and desirable for reproducibility.
- Operator output becomes readable without sacrificing exact artifact identity.
- Components that publish semantic releases can continue to use release adapters.
- Components that publish only moving container tags are represented as channels, not falsely as semantic versions.
- A future compatibility/support layer can decide whether a discovered release or tag is supported before it becomes selectable or executable.
