#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Structural tests for the normalized repository, documentation and CLI layout."""

from __future__ import annotations
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def tracked_files():
    result = subprocess.run(["git", "ls-files"], cwd=ROOT, text=True, capture_output=True, check=True)
    return set(result.stdout.splitlines())


class RepositoryLayoutTests(unittest.TestCase):
    def test_python_tests_live_under_the_tests_tree(self):
        files = tracked_files()
        offenders = []
        for item in files:
            path = Path(item)
            parts = path.parts
            if not path.name.startswith("test_") or path.suffix != ".py":
                continue
            if parts[0] != "tests":
                offenders.append(item)
                continue
            if len(parts) == 2:
                continue
            if len(parts) == 3:
                continue
            offenders.append(item)
        self.assertEqual(sorted(offenders), [])

    def test_no_python_tests_live_inside_src(self):
        files = tracked_files()
        self.assertFalse(any(p.startswith("src/") and Path(p).name.startswith("test_") for p in files))

    def test_dr_tests_do_not_shadow_production_dr_module(self):
        files = tracked_files()
        self.assertNotIn("tests/dr/dr.py", files)
        self.assertTrue(
            any(
                p.startswith("tests/backup/") or p.startswith("tests/restore/") or p.startswith("tests/common/")
                for p in files
            )
        )
        self.assertIn("src/local_ai_cli/backup/_planner.py", files)
        self.assertFalse(any(p.startswith("commands/") for p in files))

    def test_documentation_and_decision_roots_are_normalized(self):
        docs = ROOT / "docs"
        for path in (
            docs,
            docs / "user-docs",
            docs / "devel-docs",
            docs / "devel-docs" / "adr",
            docs / "devel-docs" / "sdr",
            docs / "devel-docs" / "openspec",
        ):
            self.assertTrue(path.is_dir())
        files = tracked_files()
        for prefix in ("adr/", "sdr/", "openspec/", "ADRs/"):
            self.assertFalse(any(p.startswith(prefix) for p in files))
        for item in ("INSTALLATION.md", "a2aknowledge.md", "pending.md"):
            self.assertNotIn(item, files)

    def test_long_form_markdown_lives_under_docs(self):
        offenders = []
        for item in tracked_files():
            path = Path(item)
            if path.suffix != ".md" or (path.parts and path.parts[0] == "docs") or path.name == "README.md":
                continue
            offenders.append(item)
        self.assertEqual(sorted(offenders), [])

    def test_recovery_schemas_are_owned_by_command_packages(self):
        files = tracked_files()
        self.assertNotIn("recovery.schema.json", files)
        self.assertIn("src/local_ai_cli/restore/recovery.schema.json", files)
        self.assertIn("src/local_ai_cli/common/backup-set.schema.json", files)
        self.assertFalse(any(p.startswith("commands/") for p in files))

    def test_historical_uppercase_document_names_do_not_return(self):
        forbidden = {"INSTALLATION.md", "STATUS.md", "MCP.md", "INTEGRATIONS.md"}
        self.assertEqual([p for p in tracked_files() if Path(p).name in forbidden], [])

    def test_python_cache_is_ignored(self):
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("__pycache__/", text)
        self.assertIn("*.py[cod]", text)

    def test_stack_readmes_remain_local_and_canonical(self):
        files = tracked_files()
        stacks = sorted(p.name for p in ROOT.glob("stack*_*") if p.is_dir())
        self.assertEqual(len(stacks), 8)
        for stack in stacks:
            canonical = f"{stack}/README.md"
            self.assertIn(canonical, files)
            alternates = [p for p in files if p.startswith(f"{stack}/README.") and p.endswith(".md") and p != canonical]
            self.assertEqual(alternates, [], stack)

    def test_local_ai_is_the_supported_root_management_cli(self):
        files = tracked_files()
        cli = ROOT / "local-ai"
        self.assertIn("local-ai", files)
        self.assertTrue(cli.stat().st_mode & 0o111)
        for package in (
            "install",
            "backup",
            "restore",
            "status",
            "doctor",
            "inventory",
            "completion",
            "upgrade",
            "lifecycle",
        ):
            self.assertTrue(any(p.startswith(f"src/local_ai_cli/{package}/") for p in files), package)
        self.assertIn("src/local_ai_cli/install-lifecycle.json", files)
        self.assertNotIn("src/local_ai_cli/install.py", files)
        self.assertFalse(any(p.startswith("commands/") for p in files))
        self.assertFalse(any(p.startswith("internal/") for p in files))
        self.assertFalse(any(p.startswith("installer/") for p in files))
        self.assertFalse(any(p.startswith("bkp-dr/") for p in files))
        self.assertNotIn("install.py", files)


if __name__ == "__main__":
    unittest.main()
