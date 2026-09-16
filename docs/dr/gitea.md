<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Stack4 / Gitea disaster-recovery qualification

> **Strategy/qualification reference — the public backup command is `./local-ai backup`.**

[← DR index](README.md) · [Current DR workflow](howto.md) · [Documentation map](../TOC.md)

Stack4 declares `gitea-state` as a managed `gitea-native-dump` recovery resource. `dr_stack4_backup.py` implements the private strategy used by the full manifest-driven backup engine.

For Stack4, dependency closure includes Stack0, so the relevant recovery point contains the required platform material and the native Gitea dump as part of the complete backup set.

## Consistency policy

A completed Stack4 backup uses a **controlled-offline** native dump. The live `gitea` container must be running before the operation.

Rootless operation is **not** an architecture requirement. Before the controlled stop, the adapter inspects the deployed Gitea container and derives the execution context needed by the helper: exact image reference, configured container user or image default, Gitea work path where available, `GITEA_CUSTOM` where configured, and the active `app.ini` path. Config-path discovery checks candidate paths derived from deployed environment/mount destinations without reading configuration contents.

If the active config path cannot be identified safely, backup fails **before** stopping Gitea. There is no fallback to historical UID/GID values, binary locations or assumed rootless/rootful paths.

The strategy then:

1. discovers execution context while Gitea is live;
2. stops only the `gitea` container with a bounded grace period;
3. creates a uniquely named helper container with no network, using the same image and Gitea-mounted volumes;
4. applies the discovered user/path/custom/config context and invokes `gitea` through the image `PATH`;
5. runs `gitea dump --type zip` while the live instance is down;
6. restarts the live `gitea` container immediately when the dump command exits, including the error path;
7. copies the dump from the stopped helper, removes the helper, validates ZIP paths/CRC, hashes artifacts and returns the artifact to the common backup-set publication pipeline.

The helper working directory and `--tempdir` are `/tmp` because the Gitea Docker backup packaging expects execution from the temporary packaging directory; this is a dump-mechanism requirement rather than a rootless assumption.

Downtime is limited to the native dump itself. ZIP copying and backup-set validation occur after Gitea has restarted. The helper exposes no ports and uses `--network none`. If the source Gitea container cannot be restarted after the controlled stop, the operation fails loudly and a completed recovery point is not published.

## Rootless and rootful portability

The runtime used for the recorded qualification was rootless. That is environment evidence, not a permanent architecture requirement. Automated coverage includes rootless-style explicit-user paths and rootful-style image-default-user/data paths.

A future change of Gitea image family, execution user, work path or configuration layout requires fresh real controlled-offline backup and isolated restore verification before that deployment is treated as DR-qualified.

## Restore verification

`dr_stack4_inspect.py` validates completed-set checksums and ZIP integrity and reports archive layout. `dr_stack4_restore_verify.py` performs an isolated reconstruction proof without touching the live Gitea runtime: it validates metadata/checksums, safely extracts the native ZIP, imports `gitea-db.sql` into a new temporary SQLite database, verifies application tables/data, discovers restored bare repositories and runs `git fsck --full --no-dangling` against each restored repository. The temporary restore tree is removed afterwards.

This proves that the Gitea application database and Git repository object stores represented in the native dump can be reconstructed from the persisted artifact. It deliberately does not replace the active Gitea runtime or start a second externally reachable Gitea service.

## Current boundary

The historical qualification milestone stated that generic `dr.py backup all` execution was blocked. That statement is retired. The public `./local-ai backup` command now invokes the private full backup entry point, which composes all currently declared managed strategies into one atomic recovery point. `dr.py` itself remains the planner/preflight implementation and intentionally keeps its direct `backup` subcommand dry-run-only.

Current qualification scope is summarized in [DR status](status.md).
