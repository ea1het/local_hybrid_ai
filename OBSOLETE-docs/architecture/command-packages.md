<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->
# Command package architecture

[← Architecture](README.md) · [Documentation map](../TOC.md)

`./local-ai` is the only public management interface.

This page describes the current package layout. It supersedes the flat `commands/` layout recorded in [ADR-0005](../devel-docs/adr/0005-unified-command-implementation-package.md), now marked superseded.

Public command ownership is split into independent packages: `install/`, `backup/`, `restore/`, `status/`, `doctor/`, `inventory/`, `completion/`, `upgrade/`; `lifecycle/` owns global/per-stack `start` and `stop`.

`--json` and `--yes` belong to the public CLI boundary and are represented by `cli.py`'s own `CLIContext`; command packages receive semantic state, not private copies of those public flags.

## Dependency rule

A command package must not depend on another command package; every command package may depend on `common/`, and `common/` must not depend on any command package. During package closure, implementation primitives required by a command are kept privately inside that package even when this temporarily duplicates code in another package. Shared abstractions are introduced only after package boundaries and behavior are independently verified, and only once the duplication has proven identical or reconcilable — for example `common/gitea_archive.py`, introduced after `backup` and `restore` both needed the same Gitea native-dump validation.

Tests for command-private behavior may live below the owning command package. Repository-wide contracts and cross-cutting integration tests live under the root `tests/` package.

`status` is operational only: stack identity, runtime state and health. Version intent, deployed/current/available identities, drift, registry discovery, selection, policy and targets belong to `upgrade`.

## Intra-package module shape

Each command package's public surface is `__init__.py` plus, where applicable, `config.py` (domain configuration, catalog and static state), `api.py` (payload construction, argparse surface and CLI-text rendering) and `engine.py` (the package's guarded-mutation engine, where one clear single engine exists). Every other module is package-private and named with a leading underscore. A package uses only the slots it needs: a package with no mutation path has no `engine.py`, and a package small enough to need no internal split may be just `__init__.py` plus `api.py`. `install/` and `upgrade/` are the current full examples of this shape; `backup/` has `engine.py` because it has exactly one mutation path, while `restore/` has none because it dispatches to four independent phases (`plan`/`drill`/`apply`/`resume`) from `api.py` directly, each to its own private module.
