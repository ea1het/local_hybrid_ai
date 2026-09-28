<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Pending work

[Current state](current-state.md)

Only active or intentionally deferred work belongs here. Completed work and implementation chronology belong in Git history; durable behaviour belongs in architecture, specification, user/developer documentation and qualification evidence.

## P0 — Operational hardening

- Package and document the external Stack6 memory-sync SSH bootstrap required when the configured Git origin needs that credential.

## P0 — Upgrade engine hardening

- The `postgres-major-upgrade` apply recipe (`src/local_ai_cli/upgrade/_postgres_major_upgrade.py`, used by Stack3 `postgresql`) has been exercised only against mocked subprocess/Docker calls (`tests/upgrade/test_postgres_major_upgrade.py`). It has never run against a real deployment. Real-runtime qualification — a representative PostgreSQL major-version transition on real infrastructure, per [upgrade executor qualification](devel-docs/upgrade-qualification.md) gate 11 — is required before this recipe is trusted in production. See [PostgreSQL DR qualification](dr/postgres.md#major-version-upgrade) for what the mechanism does and what it deliberately does not clean up automatically.

## P1 — Engine hardening

- Reject boolean `schema_version` explicitly rather than accepting Python's `True == 1` equivalence.
- Ensure every adapter completes fallible integrity checks before te
