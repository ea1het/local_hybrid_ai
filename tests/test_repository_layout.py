# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Structural tests for the normalized repository, documentation and CLI layout.

These tests prevent historical top-level implementation/documentation roots from
returning, allow command-private tests to live with their owning package, preserve
local canonical stack READMEs, protect package-owned recovery schemas and verify
``local-ai`` remains the supported root management entry point.
"""
from __future__ import annotations
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
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
  self.assertFalse((ROOT/"tests"/"dr").exists());self.assertTrue((ROOT/"tests"/"disaster_recovery").is_dir());self.assertTrue((ROOT/"commands"/"backup"/"dr.py").is_file());self.assertFalse((ROOT/"commands"/"recovery").exists())
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
  self.assertFalse((ROOT/"recovery.schema.json").exists());self.assertTrue((ROOT/"commands"/"restore"/"recovery.schema.json").is_file());self.assertTrue((ROOT/"commands"/"backup"/"backup-set.schema.json").is_file());self.assertFalse((ROOT/"commands"/"recovery").exists())
 def test_historical_uppercase_document_names_do_not_return(self):
  forbidden={"INSTALLATION.md","STATUS.md","MCP.md","INTEGRATIONS.md"};self.assertEqual([str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and p.name in forbidden],[])
 def test_python_cache_is_ignored(self):
  text=(ROOT/".gitignore").read_text(encoding="utf-8");self.assertIn("__pycache__/",text);self.assertIn("*.py[cod]",text)
 def test_stack_readmes_remain_local_and_canonical(self):
  stacks=sorted(p for p in ROOT.glob("stack*_*") if p.is_dir());self.assertEqual(len(stacks),8)
  for stack in stacks:self.assertTrue((stack/"README.md").is_file(),stack.name);self.assertEqual(list(stack.glob("README.*.md")),[],stack.name)
 def test_local_ai_is_the_supported_root_management_cli(self):
  cli=ROOT/"local-ai";self.assertTrue(cli.is_file());self.assertTrue(cli.stat().st_mode&0o111);commands=ROOT/"commands";self.assertTrue(commands.is_dir())
  for package in ("install","backup","restore","status","doctor","inventory","completion","upgrade","lifecycle"):self.assertTrue((commands/package).is_dir(),package)
  self.assertTrue((commands/"install-lifecycle.json").is_file());self.assertFalse((commands/"install.py").exists());self.assertFalse((commands/"recovery").exists());self.assertFalse((ROOT/"internal").exists());self.assertFalse((ROOT/"installer").exists());self.assertFalse((ROOT/"bkp-dr").exists());self.assertFalse((ROOT/"install.py").exists())
if __name__=="__main__":unittest.main()
