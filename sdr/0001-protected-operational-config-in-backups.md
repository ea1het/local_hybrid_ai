# SDR-0001 — Protected operational configuration in DR backups

Status: accepted

## Risk

A complete recovery requires identity-bearing configuration, including secrets. Losing it can make persistent application state unusable; storing it unencrypted in a backup increases confidentiality impact if the backup repository is exposed.

## Decision

Until encrypted/off-host backup handling is implemented, complete DR sets include an exact copy of the operational `.env` as a sensitive global artifact. Backup roots are private (`0700`), sensitive files are `0600`, values are never printed into metadata/logs, and the artifact is checksummed.

## Residual risk

Local backup media remains plaintext at rest. Encryption, retention and off-host policy remain active hardening work.

## Related

- `adr/0001-backup-operational-env.md`
- `docs/dr/howto.md`
- `tests/dr/test_dr_backup_all.py`
