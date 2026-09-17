<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->
# Command package architecture

[← Architecture](README.md) · [Documentation map](../TOC.md)

`./local-ai` is the only public management interface.

Public command ownership is split into independent packages: `install/`, `backup/`, `restore/`, `status/`, `doctor/`, `inventory/`, `completion/`, `upgrade/`; `lifecycle/` owns global/per-stack `start` and `stop`.

`--json` and `--yes` belong to the public CLI boundary and are represented by `CommandContext`; command packages receive semantic state, not private copies of those public flags.

## Dependency rule

A command package must not depend on another command package. During package closure, implementation primitives required by a command are kept privately inside that package even when this temporarily duplicates code in another package. Shared abstractions are introduced only after package boundaries and behavior are independently verified.

Tests for command-private behavior may live below the owning command package. Repository-wide contracts and cross-cutting integration tests live under the root `tests/` package.

`status` is operational only: stack identity, runtime state and health. Version intent, deployed/current/available identities, drift, registry discovery, selection, policy and targets belong to `upgrade`.
