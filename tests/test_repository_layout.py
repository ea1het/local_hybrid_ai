from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RepositoryLayoutTests(unittest.TestCase):
    def test_all_python_tests_live_under_root_tests(self):
        offenders = []
        for path in ROOT.rglob("test_*.py"):
            rel = path.relative_to(ROOT)
            if not rel.parts or rel.parts[0] != "tests":
                offenders.append(str(rel))
        self.assertEqual(offenders, [])

    def test_dr_tests_do_not_shadow_production_dr_module(self):
        self.assertFalse((ROOT / "tests" / "dr").exists())
        self.assertTrue((ROOT / "tests" / "disaster_recovery").is_dir())
        self.assertTrue((ROOT / "commands" / "recovery" / "dr.py").is_file())

    def test_documentation_and_decision_roots_are_normalized(self):
        docs = ROOT / "docs"
        self.assertTrue(docs.is_dir())
        self.assertTrue((docs / "user-docs").is_dir())
        self.assertTrue((docs / "devel-docs").is_dir())
        self.assertTrue((docs / "devel-docs" / "adr").is_dir())
        self.assertTrue((docs / "devel-docs" / "sdr").is_dir())
        self.assertTrue((docs / "devel-docs" / "openspec").is_dir())
        self.assertFalse((ROOT / "adr").exists())
        self.assertFalse((ROOT / "sdr").exists())
        self.assertFalse((ROOT / "openspec").exists())
        self.assertFalse((ROOT / "ADRs").exists())
        self.assertFalse((ROOT / "INSTALLATION.md").exists())
        self.assertFalse((ROOT / "a2aknowledge.md").exists())
        self.assertFalse((ROOT / "pending.md").exists())

    def test_long_form_markdown_lives_under_docs(self):
        offenders = []
        for path in ROOT.rglob("*.md"):
            rel = path.relative_to(ROOT)
            if rel.parts[0] == "docs":
                continue
            if path.name == "README.md":
                continue
            offenders.append(str(rel))
        self.assertEqual(offenders, [])

    def test_recovery_schema_is_owned_by_recovery_commands(self):
        self.assertFalse((ROOT / "recovery.schema.json").exists())
        self.assertTrue((ROOT / "commands" / "recovery" / "recovery.schema.json").is_file())

    def test_historical_uppercase_document_names_do_not_return(self):
        forbidden = {"INSTALLATION.md", "STATUS.md", "MCP.md", "INTEGRATIONS.md"}
        offenders = [
            str(path.relative_to(ROOT))
            for path in ROOT.rglob("*")
            if path.is_file() and path.name in forbidden
        ]
        self.assertEqual(offenders, [])

    def test_python_cache_is_ignored(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("__pycache__/", gitignore)
        self.assertIn("*.py[cod]", gitignore)

    def test_stack_readmes_remain_local_and_canonical(self):
        stacks = sorted(path for path in ROOT.glob("stack*_*") if path.is_dir())
        self.assertEqual(len(stacks), 8)
        for stack in stacks:
            self.assertTrue((stack / "README.md").is_file(), stack.name)
            self.assertEqual(list(stack.glob("README.*.md")), [], stack.name)

    def test_local_ai_is_the_supported_root_management_cli(self):
        cli = ROOT / "local-ai"
        self.assertTrue(cli.is_file())
        self.assertTrue(cli.stat().st_mode & 0o111)
        commands = ROOT / "commands"
        self.assertTrue(commands.is_dir())
        self.assertTrue((commands / "install.py").is_file())
        self.assertTrue((commands / "install-lifecycle.json").is_file())
        self.assertTrue((commands / "upgrade-components.json").is_file())
        self.assertTrue((commands / "recovery" / "dr.py").is_file())
        self.assertFalse((ROOT / "internal").exists())
        self.assertFalse((ROOT / "installer").exists())
        self.assertFalse((ROOT / "bkp-dr").exists())
        self.assertFalse((ROOT / "install.py").exists())


if __name__ == "__main__":
    unittest.main()
