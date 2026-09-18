<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# DR archive adapter qualification history

> **Historical qualification record — not a current operator procedure.**

[← DR index](README.md) · [Current DR workflow](howto.md) · [Documentation map](../TOC.md)

This document records the milestone that first qualified the bounded `archive` recovery strategy using Stack0 PKI. The current operator backup boundary is `./local-ai backup`, which executes the manifest-driven full backup path. The private `dr_archive.py` helper remains an implementation component and is not a supported public command.

## Qualified resource

The milestone exercised the Stack0 manifest resource:

```text
resource_id   platform-pki
strategy      archive
source        ${BASE_PATH}/service_-_platform/pki
restore       pre-prepare
sensitive     true
```

The source is read-only. Archive creation does not modify PKI files or require application-state mutation.

## Publication contract established by the milestone

The milestone established the private same-filesystem staging/publication pattern now reused by the full backup engine:

```text
backup-YYYYMMDDTHHMMSSZ/
├── backup.json
├── checksums.sha256
└── artifacts/
    └── stack0/
        └── platform-pki.tar
```

The completed set uses private directory/file permissions, bounded relative archive members, SHA-256 integrity metadata and no secret material in metadata. Publication is no-replace and atomic at the final backup-set boundary; an existing completed set is never overwritten.

Regular files, directories and symbolic links are supported by the archive contract. Special files such as sockets, devices and FIFOs fail closed.

## Current relationship to the full backup path

The early milestone intentionally allowed only Stack0 while PostgreSQL, Gitea and multi-stack execution were still being developed. Those restrictions are **retired**. Stack3 PostgreSQL, Stack4 Gitea and the full manifest-driven backup path are now implemented and qualified. `src/local_ai_cli/recovery/backup-all.py` is the private execution entry used by the public `./local-ai backup` command.

The archive adapter continues to provide the bounded archive strategy within that larger pipeline. Its historical standalone invocation is retained only as implementation/qualification context and is not an operator interface.

## Evidence retained

The milestone established evidence that remains relevant to the current contract:

- source PKI remains unchanged by backup;
- completed backup sets use private permissions;
- TAR members are bounded relative paths;
- artifact size and SHA-256 match metadata;
- `checksums.sha256` verifies artifacts and metadata;
- `backup.json` satisfies the checked-in schema;
- temporary staging directories are removed on failure/success as applicable;
- backup creation does not restart unrelated application containers.

Current end-to-end qualification scope is summarized in [DR status](status.md).
