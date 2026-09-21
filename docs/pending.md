<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Pending work

[← Documentation map](TOC.md) · [Current state](current-state.md)

Only active or intentionally deferred work belongs here. Completed work and implementation chronology belong in Git history; durable behaviour belongs in architecture, specification, user/developer documentation and qualification evidence.

## P0 — DR operational hardening

- Define backup encryption-at-rest, retention generations, off-host copy and verification policy.
- Package and document the external Stack6 memory-sync SSH bootstrap required when the configured Git origin needs that credential.

## P0 — Upgrade engine hardening

- The `postgres-major-upgrade` apply recipe (`src/local_ai_cli/upgrade/_postgres_major_upgrade.py`, used by Stack3 `postgresql`) has been exercised only against mocked subprocess/Docker calls (`tests/upgrade/test_postgres_major_upgrade.py`). It has never run against a real deployment. Real-runtime qualification — a representative PostgreSQL major-version transition on real infrastructure, per [upgrade executor qualification](devel-docs/upgrade-qualification.md) gate 11 — is required before this recipe is trusted in production. See [PostgreSQL DR qualification](dr/postgres.md#major-version-upgrade) for what the mechanism does and what it deliberately does not clean up automatically.

## P1 — DR engine hardening

- Harden recovery validation for malformed non-string `mode`, `class` and `strategy` values.
- Reject boolean `schema_version` explicitly rather than accepting Python's `True == 1` equivalence.
- Ensure every adapter completes fallible integrity checks before terminal atomic publication.
- Add Stack4 helper failure-path tests covering dump, restart, health, helper cleanup and combined failure.
- Reassess remaining compatibility project-root/symlink assumptions and replace them only where a concrete recovery path still depends on them.
- Normalize global-artifact access around `resource_id` where current recovery contracts still expose inconsistent access patterns.
- Keep bounded/resumable recovery fail-closed; managed state is never blindly re-imported after a late failure.

The earlier proposal to introduce a generic managed-restore adapter registry solely to remove stack-number specialization is no longer active work. The current recovery phases retain explicit, locally auditable specialization unless a concrete functional requirement justifies a new abstraction.

## P1 — Installer/platform hardening

- Add a common installer concurrency lock.
- Decide whether Stack6 `04-gitmem` remains an explicit operation or gains a normalized lifecycle representation.
- Keep `.lock` semantics as PREPARED only.

## P1 — CLI/documentation contract

- Extend documentation-contract coverage from structural navigation to public-command coverage so every top-level `local-ai` command, including `completion`, is represented by the CLI command map and canonical documentation.

The existing `tests/repository/test_documentation_contract.py` already validates documentation-directory indexes, TOC backlinks, relative links, Mermaid fences, Gherkin scope documentation and publication hygiene; this item concerns semantic public-command coverage beyond those existing checks.

## P2 — Upgrade engine hardening

- Registry-driven version discovery (`upgrade/_registry.py`) compares tag numbers purely arithmetically; it has no concept of versioning-scheme identity. A component under `manual` upgrade policy whose upstream registry adopts an incompatible numbering convention with a numerically larger leading segment (for example a switch from SemVer to date-based tags) can be misreported as having a newer version available, even though the two tag lineages are not comparable. `minor-series`/`major-series` policies already reject this via their own major-number check; only `manual` policy is exposed. No generic registry-side signal distinguishes versioning schemes, so this remains an accepted, narrow residual risk rather than an open defect.

## P2 — Operations

- Define retention and cleanup treatment for historical local backup sets; verified recovery evidence must not be deleted incidentally.
- Define an operator-owned cleanup policy for migration dumps, migration markers and destructive-recovery test material without embedding host-specific absolute paths or temporary artifact names in repository documentation. This now has a concrete instance: a successful `postgres-major-upgrade` deliberately leaves the pre-upgrade PostgreSQL data directory (`<name>.pre-upgrade-<timestamp>`) in place indefinitely; deciding when it is safe to delete, and whether to automate that decision, is unresolved.

## P2 — Documentation maintenance

- Keep [current-state.md](current-state.md), [management-plane architecture](architecture/management-plane.md) and [OpenSpec traceability](devel-docs/openspec/traceability.md) synchronized when public command families or major internal responsibility boundaries are added or retired.
- During structural migrations, canonical documentation is searched for retired path/command names; historical references remain only in ADR/history/restore-compatibility context where they are intentional.
- Human-facing prose remains third-person and role-oriented. Agent-oriented documents remain explicit exceptions rather than silently becoming the default writing style.
