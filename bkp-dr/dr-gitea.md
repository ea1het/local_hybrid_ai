# Stack4 / Gitea disaster recovery

Stack4 declares `gitea-state` as a managed `gitea-native-dump` recovery resource. The real backup adapter is `dr_stack4_backup.py`.

For requested Stack4, dependency closure is `[0, 4]`, so each completed backup set contains both the Stack0 platform PKI and the native Gitea dump:

```text
backup-YYYYMMDDTHHMMSSZ/
├── backup.json
├── checksums.sha256
└── artifacts/
    ├── stack0/platform-pki.tar
    └── stack4/gitea-state.zip
```

## Consistency policy

A completed Stack4 backup uses a **controlled-offline** native dump. The live `gitea` container must be running before the operation.

Rootless operation is **not** part of the recovery contract. Before the controlled stop, the adapter inspects the deployed Gitea container and derives the execution context needed by the helper:

- exact image reference;
- configured container user when one is explicitly set, otherwise the image default user is preserved;
- Gitea work path when available from the deployed environment/container configuration;
- `GITEA_CUSTOM` when configured;
- the active `app.ini` path, discovered by checking candidate paths derived from the deployed environment and mount destinations without reading the file contents.

If the active config path cannot be identified safely, the backup fails **before** stopping Gitea. There is no fallback to historical rootless/rootful paths, UID/GID values or binary locations.

The adapter then:

1. discovers the execution context described above while Gitea is live;
2. stops only the `gitea` container with a bounded grace period;
3. creates a uniquely named helper container with no network, using the same image and Gitea-mounted volumes;
4. applies the discovered user/path/custom/config context to the helper and invokes `gitea` through the image `PATH`;
5. runs `gitea dump --type zip` in that helper while the live instance is down;
6. restarts the live `gitea` container immediately when the dump command exits, including the error path;
7. copies the dump from the stopped helper, removes the helper, validates ZIP paths/CRC, hashes artifacts, validates metadata and atomically publishes the backup set.

The helper working directory and `--tempdir` are `/tmp` because Gitea's Docker backup packaging expects execution from the temporary packaging directory; this is a dump-mechanism requirement, not a rootless assumption.

The downtime is limited to the native dump itself; ZIP copying and backup-set validation happen after Gitea has been restarted. The helper exposes no ports and uses `--network none`.

If the source Gitea container cannot be restarted after the controlled stop, the adapter fails loudly and does not publish a completed backup set.

## Rootless and rootful portability

The currently deployed and real-world validated instance is rootless. That fact is evidence about the present environment, not a permanent architecture requirement.

Unit coverage includes both:

- a rootless-style context with explicit `1000:1000`, `/var/lib/gitea` and `/etc/gitea/app.ini`;
- a rootful-style context that uses the image-default user and a `/data/.../conf/app.ini` layout.

Any future change of Gitea image family, rootless/rootful mode, user, work path or config layout must be followed by a fresh real controlled-offline backup and isolated restore verification before the new deployment is considered DR-qualified.

## Restore verification

`dr_stack4_inspect.py` validates completed-set checksums and ZIP integrity and reports the archive layout.

`dr_stack4_restore_verify.py` performs an isolated reconstruction proof without touching the live Gitea runtime. It validates metadata and checksums, safely extracts the native ZIP into a private temporary directory, imports `gitea-db.sql` into a brand-new temporary SQLite database, verifies application tables/data, discovers restored bare repositories under `repos/`, and runs `git fsck --full --no-dangling` against every restored repository. The complete temporary restore tree is removed afterwards.

This proves the two critical durable stores represented in the native dump—the Gitea application database and Git repository object stores—can be reconstructed from the persisted artifact. It deliberately does not replace the active Gitea runtime and does not start a second externally reachable Gitea service.

The generic `dr.py backup all` path remains blocked until the remaining recovery contracts are closed and the all-stacks execution path is explicitly enabled.
