<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# DR filesystem qualification history

> **Historical qualification record — not a current operator procedure.**

[← DR index](README.md) · [Current DR workflow](howto.md) · [Documentation map](../TOC.md)

This document records the filesystem milestone that established the backup-root safety and publication assumptions used by later recovery adapters. The current operator entry point is `./local-ai backup`; `dr_filesystem.py` is a private implementation helper rather than a public management command.

## Destination contract

The recovery implementation resolves a backup destination with this precedence:

```text
--destination
> DR_BACKUP_ROOT
> /opt/local-hybrid-ai-backups
```

A destination is absolute, cannot be `/`, and is preflighted against protected source/runtime roots before backup execution. Equal, descendant and ancestor overlap with those protected roots is rejected.

The persistent backup root is private and owned by the executing identity. The established default contract is:

```text
/opt/local-hybrid-ai-backups/    0700
```

An existing root with incompatible ownership or permissions fails closed rather than being silently changed.

## Publication properties established by the milestone

The milestone proved the same-parent filesystem operations required by the later backup-set creator. Current completed backup publication uses private staging below the selected backup root and publishes only after artifact and integrity validation.

The resulting permission model is:

```text
backup root                0700
backup-set directory       0700
private artifact/metadata  0600
```

Completed sets use the stable pattern:

```text
backup-YYYYMMDDTHHMMSSZ
```

An existing final name is never silently replaced.

## Historical atomicity probe

The private filesystem helper originally qualified same-parent rename semantics with a transient non-secret marker/directory probe. That probe was not a backup and never represented a recovery point. Its purpose was to establish filesystem suitability before real adapters were enabled.

The full backup implementation now owns the actual staging, integrity and atomic no-replace publication path. The early “future backup-set” language and “no backup artifact created” limitation are therefore retired milestone statements, not current platform behaviour.

## Safety boundary

Filesystem preparation does not inspect secret values or mutate application data. Current destination/source preflight is additionally separated into the read-only recovery-preflight responsibility before backup mutation begins.

Current recovery phases and operator commands are documented in [the DR workflow](howto.md); qualified runtime evidence is summarized in [DR status](status.md).
