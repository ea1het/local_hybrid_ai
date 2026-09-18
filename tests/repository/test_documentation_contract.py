#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Repository-level tests that keep documentation discoverable and publication-safe.

The contract is intentionally structural rather than a prose style checker: Python
modules must have module docstrings, documentation directories must expose a local
README, Gherkin feature files must explain their behavioural scope, Markdown
navigation must resolve inside the repository, Mermaid blocks must use supported
fenced syntax, and public documentation must avoid common forms of deployment-local
operational residue. Human review remains responsible for clarity and editorial
quality.
"""

from __future__ import annotations

import ast
import re
import unittest
import urllib.parse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


class DocumentationContractTests(unittest.TestCase):
    """Protect the minimum navigability, source-documentation and publication contract."""

    def test_every_python_module_has_module_docstring(self):
        excluded_parts = {".git", "__pycache__"}
        python_files = [
            path
            for path in ROOT.rglob("*.py")
            if not any(part in excluded_parts for part in path.parts)
        ]
        self.assertTrue(python_files)
        missing: list[str] = []
        for path in sorted(python_files):
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if not ast.get_docstring(module, clean=False):
                missing.append(str(path.relative_to(ROOT)))
        self.assertEqual(missing, [], f"Python modules without module docstrings: {missing}")

    def test_every_docs_directory_has_readme(self):
        missing = []
        for directory in sorted(path for path in DOCS.rglob("*") if path.is_dir()):
            if not (directory / "README.md").is_file():
                missing.append(str(directory.relative_to(ROOT)))
        self.assertEqual(missing, [], f"Documentation directories without README.md: {missing}")

    def test_docs_readmes_link_back_to_canonical_toc(self):
        missing = []
        for readme in sorted(DOCS.rglob("README.md")):
            if readme == DOCS / "README.md":
                continue
            text = readme.read_text(encoding="utf-8")
            if "TOC.md" not in text:
                missing.append(str(readme.relative_to(ROOT)))
        self.assertEqual(missing, [], f"Documentation README files without TOC link: {missing}")

    def test_relative_markdown_links_resolve_inside_repository(self):
        """Catch broken TOC/cross-links while ignoring anchors and external URLs."""
        broken: list[str] = []
        markdown_files = [ROOT / "README.md", *sorted(DOCS.rglob("*.md"))]
        link_re = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
        for markdown in markdown_files:
            text = markdown.read_text(encoding="utf-8")
            for raw_target in link_re.findall(text):
                target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
                if not target or target.startswith("#"):
                    continue
                parsed = urllib.parse.urlsplit(target)
                if parsed.scheme or parsed.netloc:
                    continue
                path_text = urllib.parse.unquote(parsed.path)
                if not path_text:
                    continue
                candidate = (markdown.parent / path_text).resolve()
                try:
                    candidate.relative_to(ROOT.resolve())
                except ValueError:
                    broken.append(f"{markdown.relative_to(ROOT)} -> {raw_target} (outside repository)")
                    continue
                if not candidate.exists():
                    broken.append(f"{markdown.relative_to(ROOT)} -> {raw_target}")
        self.assertEqual(broken, [], f"Broken relative Markdown links: {broken}")

    def test_gherkin_features_have_scope_documentation(self):
        missing = []
        for feature in sorted((DOCS / "devel-docs" / "openspec").rglob("*.feature")):
            text = feature.read_text(encoding="utf-8")
            lines = [line.rstrip() for line in text.splitlines()]
            feature_index = next((i for i, line in enumerate(lines) if line.startswith("Feature:")), None)
            if feature_index is None:
                missing.append(str(feature.relative_to(ROOT)))
                continue
            explanatory = [
                line.strip()
                for line in lines[feature_index + 1 :]
                if line.strip() and not line.lstrip().startswith(("#", "@"))
            ]
            if not explanatory or explanatory[0].startswith(("Rule:", "Scenario:", "Background:")):
                missing.append(str(feature.relative_to(ROOT)))
        self.assertEqual(missing, [], f"Gherkin feature files without explanatory scope text: {missing}")

    def test_mermaid_fences_declare_supported_diagram_type(self):
        invalid = []
        fence = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
        for markdown in sorted(ROOT.rglob("*.md")):
            text = markdown.read_text(encoding="utf-8")
            for block in fence.findall(text):
                first = next((line.strip() for line in block.splitlines() if line.strip()), "")
                if not first.startswith(("flowchart ", "graph ", "sequenceDiagram", "stateDiagram", "classDiagram", "erDiagram", "journey", "gantt", "pie ", "mindmap", "timeline", "gitGraph")):
                    invalid.append(f"{markdown.relative_to(ROOT)}: {first or '<empty>'}")
        self.assertEqual(invalid, [], f"Unsupported/undocumented Mermaid block starts: {invalid}")

    def test_docs_avoid_deployment_local_operational_residue(self):
        """Keep private-host artifacts and milestone diaries out of canonical docs."""
        violations: list[str] = []
        private_path = re.compile(r"/(?:root|home/[^/\s`]+)/[^\s`]+")
        timestamped_backup = re.compile(r"\bbackup-\d{8}T\d{6}Z\b")
        closeout_name = re.compile(r"point\d+-closeout\.md$", re.IGNORECASE)

        for markdown in sorted(DOCS.rglob("*.md")):
            relative = markdown.relative_to(ROOT).as_posix()
            if closeout_name.search(markdown.name):
                violations.append(f"{relative}: milestone closeout document")
                continue
            text = markdown.read_text(encoding="utf-8")
            if private_path.search(text):
                violations.append(f"{relative}: host-specific home-directory path")
            if timestamped_backup.search(text):
                violations.append(f"{relative}: timestamped backup identifier")
            if "## Recently closed" in text:
                violations.append(f"{relative}: completed-work diary belongs in Git history")

        self.assertEqual(violations, [], f"Deployment-local documentation residue: {violations}")


if __name__ == "__main__":
    unittest.main()
