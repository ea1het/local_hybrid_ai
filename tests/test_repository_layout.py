# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Structural tests for the normalized repository, documentation and CLI layout."""
from __future__ import annotations
import subprocess
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def tracked_files():
 result=subprocess.run(["git","ls-files"],cwd=ROOT,text=True,capture_output=True,check=True)
 return set(result.stdout.splitlines())
class RepositoryLayoutTests(unittest.TestCase):
 def test_python_tests_live_at_root_or_with_command_owner(self):
  offenders=[]
  for path in ROOT.rglob("test_*.py"):
   rel=path.relative_to(ROOT);parts=rel.parts
   if parts and parts[0]=="tests":continue
   if len(parts)>=4 and parts[0]=="commands" and parts[2]=="tests":continue
   offenders.append(str(rel))
  self.assertEqual(offenders,[])
 def test_dr_tests_do_not_shadow_production_dr_module(self):
  files=tracked_files();self.assertNotIn("tests/dr/dr.py",files);self.assertTrue((ROOT/"tests"/"disaster_recovery").is_dir());self.assertIn("commands/backup/dr.py",files);self.assertFalse(any(p.startswith("commands/recovery/") for p in files))
 def test_documentation_and_decision_roots_are_normalized(self):
  docs=ROOT/"docs"
  for path in (docs,docs/"user-docs",docs/"devel-docs",docs/"devel-docs"/"adr",docs/"devel-docs"/"sdr",docs/"devel-docs"/"openspec"):self.assertTrue(path.is_dir())
  for path in (ROOT/"adr",ROOT/"sdr",ROOT/"openspec",ROOT/"ADRs",ROOT/"INSTALLATION.md",ROOT/"a2aknowledge.md",ROOT/"pending.md"):self.assertFalse(path.exists())
 def test_long_form_markdown_lives_under_docs(self):
  offenders=[]
  for path in ROOT.rglob("*.md"):
   rel=path.relative_to(ROOT)
   if rel.parts[0]=="docs" or path.name=="README.md":continue
   offenders.append(str(rel))
  self.assertEqual(offenders,[])
 def test_recovery_schemas_are_owned_by_command_packages(self):
  files=tracked_files();self.assertNotIn("recovery.schema.json",files);self.assertIn("commands/restore/recovery.schema.json",files);self.assertIn("commands/backup/backup-set.schema.json",files);self.assertFalse(any(p.startswith("commands/recovery/") for p in files))
 def test_historical_uppercase_document_names_do_not_return(self):
  forbidden={"INSTALLATION.md","STATUS.md","MCP.md","INTEGRATIONS.md"};self.assertEqual([str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and p.name in forbidden],[])
 def test_python_cache_is_ignored(self):
  text=(ROOT/".gitignore").read_text(encoding="utf-8");self.assertIn("__pycache__/",text);self.assertIn("*.py[cod]",text)
 def test_stack_readmes_remain_local_and_canonical(self):
  stacks=sorted(p for p in ROOT.glob("stack*_*") if p.is_dir());self.assertEqual(len(stacks),8)
  for stack in stacks:self.assertTrue((stack/"README.md").is_file(),stack.name);self.assertEqual(list(stack.glob("README.*.md")),[],stack.name)
 def test_local_ai_is_the_supported_root_management_cli(self):
  files=tracked_files();cli=ROOT/"local-ai";self.assertTrue(cli.is_file());self.assertTrue(cli.stat().st_mode&0o111);commands=ROOT/"commands";self.assertTrue(commands.is_dir())
  for package in ("install","backup","restore","status","doctor","inventory","completion","upgrade","lifecycle"):self.assertTrue((commands/package).is_dir(),package)
  self.assertIn("commands/install-lifecycle.json",files);self.assertNotIn("commands/install.py",files);self.assertFalse(any(p.startswith("commands/recovery/") for p in files));self.assertFalse(any(p.startswith("internal/") for p in files));self.assertFalse(any(p.startswith("installer/") for p in files));self.assertFalse(any(p.startswith("bkp-dr/") for p in files));self.assertNotIn("install.py",files)
if __name__=="__main__":unittest.main()
