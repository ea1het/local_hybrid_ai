# DR archive adapter — first executing backup milestone

This milestone introduces the first real disaster-recovery artifact writer while deliberately keeping PostgreSQL, Gitea and multi-stack backup execution disabled.

The executable is:

```bash
python3 dr_archive.py 0 --destination /opt/local-hybrid-ai-backups
```

It resolves the normal manifest dependency plan and currently fails closed unless that plan is exactly Stack0. This is a temporary milestone gate: the implementation proves one strategy end-to-end before additional adapters are enabled.

## Scope

The only executing recovery resource is the Stack0 manifest resource:

```text
resource_id   platform-pki
strategy      archive
source        ${BASE_PATH}/service_-_platform/pki
restore       pre-prepare
sensitive     true
```

The source is read-only. The adapter does not modify PKI files, restart containers, invoke Docker, dump PostgreSQL, or invoke Gitea.

## Preconditions

Before artifact creation the command reuses the existing DR contracts:

1. resolve manifests and dependency plan;
2. resolve destination using `--destination > DR_BACKUP_ROOT > /opt/local-hybrid-ai-backups`;
3. run destination preflight;
4. run runtime/source preflight;
5. validate or create the private backup root using the filesystem contract.

The backup root must therefore satisfy the already-validated `0700`, same-owner filesystem contract.

## Backup-set publication

A successful run creates a private temporary sibling directory below the backup root:

```text
.backup-YYYYMMDDTHHMMSSZ.tmp-<random>/
```

and builds:

```text
backup.json
checksums.sha256
artifacts/
└── stack0/
    └── platform-pki.tar
```

Directory mode is `0700`. Archive, metadata and checksum files are `0600`.

The archive contains the bounded PKI source using its source basename as archive root (`pki/...`). Absolute archive member names are not used. Regular files, directories and symbolic links are supported; special files such as sockets/devices/FIFOs fail closed.

## Integrity and metadata

After the archive is fsynced the adapter calculates its real SHA-256 and byte size. `backup.json` is then generated and validated against the checked-in `backup-set.schema.json` contract before publication.

`checksums.sha256` records:

```text
SHA256  artifacts/stack0/platform-pki.tar
SHA256  backup.json
```

No secret values or PKI contents are copied into metadata.

## Atomic publication and collision safety

The temporary backup set is fsynced before publication. Final publication uses Linux `renameat2(..., RENAME_NOREPLACE)` into:

```text
backup-YYYYMMDDTHHMMSSZ/
```

This provides two required properties at the publication boundary:

- same-filesystem atomic rename;
- an existing final backup-set name is never replaced.

If `renameat2` is unavailable, execution fails closed rather than falling back to overwrite-capable semantics.

After publication the backup root is fsynced and the published archive checksum is read back and compared with the recorded hash.

On a pre-publication error, only the uniquely-created hidden temporary directory is removed. An already-existing final backup set is never removed or modified.

## Current execution boundary

This milestone intentionally does **not** enable:

```text
postgres-custom-dump
gitea-native-dump
multi-stack real backup
dr.py backup without --dry-run
restore execution
```

`dr.py backup ... --dry-run` remains the general planner/preflight interface. `dr_archive.py` is the explicit first executing adapter while the execution pipeline is validated on the real host.

## Host validation goals

The first real Stack0 backup should prove:

```text
source PKI inode/mode/hash unchanged before vs after
+ completed timestamped backup-set exists
+ final directory mode 0700
+ artifact/metadata/checksum mode 0600
+ TAR contains only bounded relative PKI tree
+ artifact SHA-256 equals backup.json
+ artifact size equals backup.json
+ checksums.sha256 verifies artifact and backup.json
+ backup.json satisfies backup-set.schema.json contract
+ no hidden temporary backup directories remain
+ no container restart or application mutation occurred
```

After this passes, the next milestone is a restore test of the archive into a temporary isolated directory. Only after proving restore should implementation move to the Stack3 `postgres-custom-dump` adapter.
