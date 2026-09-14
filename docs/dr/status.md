<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# DR qualification status

This document summarizes disaster-recovery capabilities that have been qualified beyond source-only inspection. It records capability-level evidence rather than environment-specific hostnames, local paths, backup identifiers or deployment content. Read it with [howto.md](howto.md), [../a2aknowledge.md](../a2aknowledge.md), [../pending.md](../pending.md), [../devel-docs/adr/](../devel-docs/adr/) and [../devel-docs/sdr/](../devel-docs/sdr/). The private DR implementation and schemas live under [`../../commands/recovery/`](../../commands/recovery/).

## Core clean-target recovery — PASS

A destructive clean-target recovery has been qualified through the supported recovery workflow. Qualification verified that:

- the recovery-point checksum index remained valid;
- restored source matched the source identity recorded by the recovery point;
- managed PostgreSQL, Gitea and external-memory prerequisites were reconstructed and verified through their adapters;
- a bounded resume could continue after recovery-tooling defects were corrected without repeating a destructive wipe or blindly re-importing already recovered managed state.

The qualification established that recovery is driven by the recorded recovery contract rather than by assumptions about pre-existing runtime state.

## Stack7 global recovery point — PASS

Global backup qualification includes the Stack7 Open WebUI artifact and required prerequisites. The recovery point was verified for complete checksums and atomic publication.

An isolated restore using the DR engine's safe archive extractor verified that the Open WebUI database and persisted application state can be reconstructed while leaving the active runtime unchanged. Verification covered user-role integrity, curated model activation and access policy, default model selection, disabled Arena behaviour, persisted interface settings and cleanup of the isolated temporary runtime.

An earlier generic archive-extraction experiment rejected a cache symlink that the supported DR extractor handles safely. The supported extractor, not an ad-hoc generic extraction call, defines restore compatibility.

## Stack7 functional qualification — PASS

A clean Stack7 deployment has qualified the following externally relevant behaviour:

- `basic_autorouter` is the configured default model;
- Arena is disabled;
- model access control remains enabled with explicit public-read policy for the curated model;
- regular-user access is limited to the intended model policy;
- Web Search is enabled by default;
- `search_web` and `fetch_url` return functional results.

Per-request correlation between SearXNG and Firecrawl is not observable in current provider logs. That is an observability limitation and is not represented as verified provider-log evidence.

## Backup destination overlap guard — PASS

Runtime qualification confirms that backup destinations are rejected before publication when they are:

- equal to a protected source or runtime root;
- descendants of a protected root; or
- ancestors that would contain a protected root.

Validation compares resolved paths, so `..` and symlink-based aliases are covered by automated tests. Rejected overlap attempts do not create temporary backup-set residue. The public contract is expressed in terms of `STACKS_ROOT` and `BASE_PATH`; deployment-specific absolute paths are intentionally not part of this document.

## Evidence retention

Verified recovery points used as qualification evidence are subject to the project's retention policy and must not be treated as generic temporary files. Detailed environment-specific chronology belongs in controlled operational records and Git history rather than public repository documentation. Destructive recovery should not be repeated solely to recreate evidence for a capability that is already recorded as qualified.
