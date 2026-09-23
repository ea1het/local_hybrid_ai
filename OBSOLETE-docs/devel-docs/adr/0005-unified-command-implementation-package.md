<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# ADR-0005 — Unified command implementation package

- Status: **Superseded** — see [current status](#current-status) below
- Date: 2026-09-13

## Current status

The package layout this ADR decided — one flat `commands/` package with modules such as `upgrade_entry.py`/`upgrade_executor.py` and a `commands/recovery/` subpackage — is not the current implementation. It was superseded by per-command packages directly under `src/local_ai_cli/` (`install/`, `backup/`, `restore/`, `status/`, `doctor/`, `inventory/`, `completion/`, `upgrade/`, `lifecycle/`), each following the `__init__.py` + `config.py`/`api.py`/`engine.py` + private-module shape described in [command package architecture](../../architecture/command-packages.md). The underlying decision this ADR still establishes — one coherent private implementation area behind the `./local-ai` boundary, with disaster recovery kept cohesive rather than flattened — remains true; only the concrete package shape below is historical. The body of this ADR is preserved as the decision record for that earlier shape and is not updated to match current paths.

## Context

`./local-ai` is already the sole supported management interface and anticorruption boundary. The implementation behind that boundary had nevertheless become split across four top-level areas: `commands/`, `internal/`, `installer/` and `bkp-dr/`. That split reflected implementation history rather than a useful external or domain boundary.

All four areas exist to implement operations exposed through the same management CLI. Keeping separate top-level roots made ownership harder to infer, encouraged path coupling, and made documentation/tests describe implementation directories that external consumers must not depend on.

Disaster recovery is larger than the other command domains: it owns several engines, adapters and schemas. Flattening every DR module directly into `commands/` would reduce rather than improve navigability.

## Decision

`./local-ai` remains the only supported management interface. All private management implementation is organized under one Python package, `commands/`.

The package is intentionally allowed to contain both modules and cohesive subpackages:

```text
commands/
├── cli.py
├── install.py
├── install-lifecycle.json
├── component_inventory.py
├── inventory.py
├── status.py
├── upgrade.py
├── upgrade_entry.py
├── upgrade_registry.py
├── upgrade_executor.py
├── upgrade_guard.py
├── upgrade_policy.py
└── recovery/
    ├── backup-all.py
    ├── restore-*.py
    ├── dr*.py
    └── *.schema.json
```

Installation, inventory, status and upgrade remain direct modules/configuration because each is a compact command domain. Component topology itself belongs to stack manifests as specified by [ADR-0007](0007-manifest-component-inventory.md), rather than to a central command-package catalog. Disaster recovery is a `commands/recovery/` subpackage because its engines, restore adapters, verification helpers and schemas form one larger cohesive domain.

There are no separate top-level `internal/`, `installer/` or `bkp-dr/` implementation roots. Stack-owned lifecycle scripts remain with their stacks because the stack owns that behavior; the command package orchestrates those lifecycle entry points rather than absorbing them.

Tests may import private command modules directly when useful, but those imports are test coupling, not an external API stability promise. External automation must continue to use `./local-ai`, using `--json` where a stable machine contract exists.

Historical disaster-recovery compatibility is an exception only for recovery of existing backup source commits. Restore code may recognize `commands/install.py`, the previous `installer/install.py`, and the older root `install.py` in recorded source trees. Recognition of a historical path does not restore that path as a supported operator interface.

## Consequences

Repository ownership is clearer: anything implementing the management CLI is found under `commands/`, except behavior explicitly owned by an atomic stack. The public boundary is unchanged, so the reorganization does not create a second management API.

The recovery subpackage preserves internal cohesion without creating another top-level architectural boundary. Implementation paths remain refactorable, while the public CLI and versioned JSON contracts carry compatibility obligations.

Repository-layout tests must enforce the absence of the historical top-level implementation roots, and OpenSpec traceability must treat the package shape as an architectural constraint of the single-CLI boundary rather than as a new public interface.
