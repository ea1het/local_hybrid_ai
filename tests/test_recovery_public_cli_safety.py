# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Focused safety regressions for the public backup/restore boundary."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from commands import cli


class RecoveryPublicCliSafetyTests(unittest.TestCase):
    def _write_set(self, root: Path, metadata: dict) -> Path:
        backup = root / "backup-20260916T120000Z"
        backup.mkdir()
        (backup / "backup.json").write_text(json.dumps(metadata), encoding="utf-8")
        (backup / "checksums.sha256").write_text("placeholder\n", encoding="utf-8")
        return backup

    def _valid_metadata(self) -> dict:
        return {
            "schema_version": 1,
            "kind": "local-hybrid-ai-backup-set",
            "created_at": "2026-09-16T12:00:00Z",
            "source_commit": "a" * 40,
            "requested": ["all"],
            "resolved_stacks": [0, 3, 6],
            "artifacts": [],
            "prerequisites": [],
        }

    def test_backup_listing_rejects_boolean_schema_version(self):
        metadata = self._valid_metadata()
        metadata["schema_version"] = True
        with tempfile.TemporaryDirectory() as tmp:
            records = cli._backup_sets(Path(tmp)) if False else None
            root = Path(tmp)
            self._write_set(root, metadata)
            records = cli._backup_sets(root)
        self.assertEqual(records[0]["status"], "invalid")

    def test_backup_listing_rejects_malformed_source_commit(self):
        metadata = self._valid_metadata()
        metadata["source_commit"] = "not-a-commit"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_set(root, metadata)
            records = cli._backup_sets(root)
        self.assertEqual(records[0]["status"], "invalid")

    def test_backup_listing_rejects_unknown_metadata_field(self):
        metadata = self._valid_metadata()
        metadata["unexpected"] = "field"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_set(root, metadata)
            records = cli._backup_sets(root)
        self.assertEqual(records[0]["status"], "invalid")

    def test_restore_execute_requires_public_clean_target_confirmation(self):
        with self.assertRaises(SystemExit) as raised, mock.patch.object(cli, "_run_internal") as run:
            cli.restore_command(["apply", "/backup/set", "--execute"], json_output=False)
        self.assertEqual(raised.exception.code, 2)
        run.assert_not_called()

    def test_restore_preflight_rejects_execution_confirmation(self):
        with self.assertRaises(SystemExit) as raised, mock.patch.object(cli, "_run_internal") as run:
            cli.restore_command(["apply", "/backup/set", "--check-clean-target", "--confirm-clean-target"], json_output=False)
        self.assertEqual(raised.exception.code, 2)
        run.assert_not_called()

    def test_restore_execute_with_confirmation_reaches_private_engine(self):
        with mock.patch.object(cli, "_run_internal", return_value=0) as run:
            rc = cli.restore_command(["apply", "/backup/set", "--execute", "--confirm-clean-target"], json_output=False)
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_args.args[1], ["/backup/set", "--execute", "--confirm-clean-target"])


if __name__ == "__main__":
    unittest.main()
