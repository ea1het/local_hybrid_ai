# DR filesystem execution contract

This document defines the filesystem-publication milestone that precedes real disaster-recovery adapters.

The helper is `dr_filesystem.py`. It does **not** run `tar`, `pg_dump`, `gitea dump`, checksum generation, restore logic, or any Docker operation. Its only persistent change is preparation of the configured backup root.

## Destination

Destination precedence matches `dr.py`:

```text
--destination
> DR_BACKUP_ROOT
> /opt/local-hybrid-ai-backups
```

Execution requires explicit opt-in:

```bash
sudo python3 dr_filesystem.py --prepare
sudo python3 dr_filesystem.py --prepare --destination /opt/local-hybrid-ai-backups
DR_BACKUP_ROOT=/mnt/backup/local-hybrid-ai sudo -E python3 dr_filesystem.py --prepare
```

The destination must be absolute and cannot be `/`.

## Persistent root contract

If the backup root does not exist, the helper creates it with a process umask of `077` and validates the resulting root as:

```text
owner = executing uid
mode  = 0700
writable/executable by executing uid
```

If the root already exists, the helper does not silently `chmod` or `chown` it. A root with a different owner or mode fails closed so the operator can inspect the situation explicitly.

For the current default this means:

```text
/opt/local-hybrid-ai-backups/    0700
```

## Future backup-set contract

A real backup set will be built in a private temporary directory under the same backup root and then published with a same-parent rename only after every artifact and integrity record succeeds.

Intended permissions:

```text
backup root                0700
backup-set directory       0700
artifact/metadata files    0600 when private/sensitive
```

The final directory name remains:

```text
backup-YYYYMMDDTHHMMSSZ
```

A final name must never be silently overwritten. Collision handling will be implemented with the executing backup-set creator, not by weakening the naming contract.

## Atomicity probe

`dr_filesystem.py --prepare` performs a transient non-secret probe inside the configured root:

1. create a private temporary directory (`0700`);
2. create and fsync a private marker file (`0600`);
3. fsync the temporary directory;
4. publish the directory with `os.replace()` to a different hidden name in the same parent;
5. fsync the backup root;
6. verify that the published directory preserved the same inode and contains the marker;
7. remove only the known probe marker/directory and fsync the root again.

The probe never recursively deletes arbitrary paths. A successful run leaves the backup root empty unless files already existed there before the probe.

The atomicity probe is evidence that the selected filesystem supports the same-parent rename primitive that the future completed backup-set publication will use. It is not a backup and must never be represented as one.

## Output guarantees

A successful result explicitly reports:

```text
root created or reused
root mode
executing owner uid
probe temporary-directory mode
probe file mode
same-parent atomic rename PASS
probe cleanup PASS
final backup set created: no
backup artifact created: no
```

JSON output carries the same facts and always marks `final_backup_set_created` and `backup_artifact_created` false for this milestone.

## Safety boundary

This helper does not inspect or modify `/opt/docker/runtime`, `.env`, containers, databases, Gitea, LiteLLM, PKI contents, or application services. It prepares only the backup destination and validates filesystem semantics.

After this contract is validated on the real host, the next milestone is adapter execution one strategy at a time, beginning with the bounded Stack0 PKI archive, while retaining fail-closed publication and no-overwrite semantics.
