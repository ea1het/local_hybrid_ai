<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# User documentation

[← Documentation map](../TOC.md)

This area contains the supported operator-facing contract for Local Hybrid AI. Operators and external automation use `./local-ai`; implementation modules under `commands/`, stack scripts and Compose files are not public management APIs.

## Start here

- [CLI reference](cli.md) — complete supported management surface, including human and JSON contracts.
- [Shell completion](completion.md) — Bash/Zsh adapters, `completion install` and persistent-install status.
- [Upgrading components](upgrade.md) — discovering, selecting, applying and recovering from component upgrades; explains selectability and explicit consent.
- [Administrator-forced upgrades](forced-upgrades.md) — explicit `--force` override for inventory-only components that already have a deterministic mutation recipe.
- [Component version authority](version-authority.md) — migration/advanced background for installations that predate installation-owned version authority.
- [Installation](../installation.md) — planning, installation and lifecycle convergence.
- [Upgrade policy](../upgrade-policy.md) — compatibility boundaries and installation policy overrides.
- [Disaster recovery](../dr/README.md) — backup, restore planning, drills and clean-target recovery.
- [Configuration and secrets](../configuration/README.md) — protected environment and secret ownership.
- [Integrations](integrations/README.md) — Hermes and LiteLLM/MCP integration guidance.

For a compact statement of what exists now and what legacy implementation surfaces have been retired, see [current implementation state](../current-state.md).

`commands/` is a private implementation package behind the CLI. Historical restore compatibility may recognize older source layouts, but those historical paths are not supported operator interfaces.

The documentation describes behaviour implemented by the current source tree. Where a command intentionally lacks a stable JSON contract, the CLI fails explicitly rather than pretending one exists.
