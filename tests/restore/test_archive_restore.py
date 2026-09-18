# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Protect safe verification and extraction semantics for DR archive artifacts."""
import datetime as dt,json,os,tempfile,unittest
from pathlib import Path
from local_ai_cli.common import archive as backup_archive
from local_ai_cli.restore import archive_restore
class DisasterRecoveryArchiveRestoreTests(unittest.TestCase):
 def make_source(self,parent):
  source=parent/"pki";source.mkdir(mode=0o700);(source/"tls.key").write_text("PRIVATE-KEY-TEST\n");(source/"tls.crt").write_text("CERTIFICATE-TEST\n");os.chmod(source/"tls.key",0o640);os.chmod(source/"tls.crt",0o644);return source
 def make_backup(self,parent,source):
  root=parent/"backups";root.mkdir(mode=0o700);os.chmod(root,0o700);artifact=backup_archive.ArchiveArtifact(stack_id=0,resource_id="platform-pki",strategy="archive",sensitive=True,restore_phase="pre-prepare",relative_path="artifacts/stack0/platform-pki.tar");return backup_archive.execute_archive_backup_set(backup_root=root,source=source,source_commit="a"*40,requested=["0"],resolved_stacks=[0],artifact=artifact,prerequisites=[],now=dt.datetime(2026,9,10,15,0,0,tzinfo=dt.timezone.utc)).path
 def test_restore_verification_matches_source_and_cleans_temp(self):
  with tempfile.TemporaryDirectory() as tmp:
   parent=Path(tmp);source=self.make_source(parent);result=archive_restore.verify_restore(self.make_backup(parent,source),compare_source=source);self.assertTrue(result.source_match);self.assertTrue(result.temporary_cleanup);self.assertEqual(result.member_count,3)
 def test_checksum_tampering_is_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   parent=Path(tmp);source=self.make_source(parent);backup=self.make_backup(parent,source);artifact=backup/"artifacts/stack0/platform-pki.tar"
   with artifact.open("ab") as h:h.write(b"tamper")
   with self.assertRaises(archive_restore.ArchiveRestoreError):archive_restore.verify_restore(backup,compare_source=source)
 def test_source_mismatch_is_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   parent=Path(tmp);source=self.make_source(parent);backup=self.make_backup(parent,source);(source/"tls.crt").write_text("CHANGED\n")
   with self.assertRaises(archive_restore.ArchiveRestoreError):archive_restore.verify_restore(backup,compare_source=source)
 def test_path_traversal_member_name_is_rejected(self):
  for name in ("../escape","/absolute","other/file"):
   with self.assertRaises(archive_restore.ArchiveRestoreError):archive_restore.safe_member_name(name)
 def test_absolute_symlink_target_is_rejected(self):
  with self.assertRaises(archive_restore.ArchiveRestoreError):archive_restore.validate_symlink_target(archive_restore.PurePosixPath("pki/link"),"/etc/passwd")
 def test_result_json_never_claims_live_restore(self):
  with tempfile.TemporaryDirectory() as tmp:
   parent=Path(tmp);source=self.make_source(parent);payload=archive_restore.verify_restore(self.make_backup(parent,source),compare_source=source).as_dict();self.assertFalse(payload["live_runtime_modified"]);self.assertTrue(payload["temporary_cleanup"]);self.assertTrue(payload["source_match"]);json.dumps(payload)
if __name__=="__main__":unittest.main()
