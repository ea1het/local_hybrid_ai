# Stack4 / Gitea disaster recovery

Stack4 declares `gitea-state` as a managed `gitea-native-dump` recovery resource.
The real backup adapter is `dr_stack4_backup.py`.

For requested Stack4, dependency closure is `[0, 4]`, so each completed backup
set contains both the Stack0 platform PKI and the native Gitea dump:

```text
backup-YYYYMMDDTHHMMSSZ/
├── backup.json
├── checksums.sha256
└── artifacts/
    ├── stack0/platform-pki.tar
    └── stack4/gitea-state.zip
```

The Gitea artifact is produced with the Gitea application's native `gitea dump`
command. The temporary native dump exists only under a uniquely named `/tmp`
path inside the Gitea container, is copied into the private backup-set staging
directory, validated as a safe ZIP with valid CRCs, and then removed from the
container. The application is not stopped or restarted.

`dr_stack4_inspect.py` validates completed-set checksums and ZIP integrity and
reports the archive's top-level entries and coarse recovery-content categories.
It does not extract or restore the archive into the live runtime.

This milestone intentionally separates **native backup proof** from **restore
proof**. The exact archive layout produced by the live Gitea 1.27.1 instance is
first captured and inspected. A subsequent milestone will implement an isolated
restore procedure against that exact layout rather than guessing Gitea's restore
semantics.

The generic `dr.py backup all` path remains blocked until all managed resources
have validated real adapters and restore procedures.
