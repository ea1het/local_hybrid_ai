# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Protect the filesystem contract used before any DR backup artifact is published."""
import os,stat,tempfile,unittest
from pathlib import Path
from local_ai_cli.common import dr_filesystem
class DisasterRecoveryFilesystemTests(unittest.TestCase):
 def test_destination_defaults_to_opt(self):
  path,source=dr_filesystem.resolve_backup_root(None,environ={});self.assertEqual(path,Path("/opt/local-hybrid-ai-backups"));self.assertEqual(source,"default")
 def test_cli_destination_overrides_environment(self):
  path,source=dr_filesystem.resolve_backup_root("/srv/backup",environ={"DR_BACKUP_ROOT":"/mnt/backup"});self.assertEqual(path,Path("/srv/backup"));self.assertEqual(source,"cli")
 def test_relative_and_root_destinations_are_rejected(self):
  with self.assertRaises(dr_filesystem.FilesystemContractError):dr_filesystem.resolve_backup_root("relative/path",environ={})
  with self.assertRaises(dr_filesystem.FilesystemContractError):dr_filesystem.resolve_backup_root("/",environ={})
 def test_prepare_creates_private_root_and_cleans_probe(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/"backup-root";result=dr_filesystem.prepare_filesystem_contract(root,"cli");self.assertTrue(result.root_created);self.assertEqual(stat.S_IMODE(root.stat().st_mode),0o700);self.assertEqual(result.probe_temp_mode,0o700);self.assertEqual(result.probe_file_mode,0o600);self.assertTrue(result.atomic_rename_ok);self.assertEqual(list(root.iterdir()),[])
 def test_existing_private_root_is_reused_without_recreation(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/"backup-root";root.mkdir(mode=0o700);os.chmod(root,0o700);result=dr_filesystem.prepare_filesystem_contract(root,"cli");self.assertFalse(result.root_created);self.assertEqual(result.root_mode,0o700)
 def test_existing_permissive_root_fails_closed_without_chmod(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/"backup-root";root.mkdir(mode=0o755);os.chmod(root,0o755)
   with self.assertRaises(dr_filesystem.FilesystemContractError):dr_filesystem.prepare_filesystem_contract(root,"cli")
   self.assertEqual(stat.S_IMODE(root.stat().st_mode),0o755)
 def test_existing_file_fails_closed(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/"backup-root";root.write_text("not a directory")
   with self.assertRaises(dr_filesystem.FilesystemContractError):dr_filesystem.prepare_filesystem_contract(root,"cli")
 def test_json_result_never_claims_backup_artifact_or_final_set(self):
  with tempfile.TemporaryDirectory() as tmp:
   result=dr_filesystem.prepare_filesystem_contract(Path(tmp)/"backup-root","cli").as_dict();self.assertFalse(result["final_backup_set_created"]);self.assertFalse(result["backup_artifact_created"]);self.assertEqual(result["root_mode"],"0700")
if __name__=="__main__":unittest.main()
