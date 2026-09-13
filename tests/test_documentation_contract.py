"""Repository-level tests that keep documentation discoverable and source files self-describing.

The contract is intentionally structural rather than stylistic: Python modules must
have module docstrings, documentation directories must expose a local README,
Gherkin feature files must explain their behavioural scope, and Markdown Mermaid
blocks must use the supported fenced form. Content quality is still reviewed by
humans; these tests prevent the most common forms of documentation regression.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


class DocumentationContractTests(unittest.TestCase):
    """Protect the minimum navigability and source-documentation contract."""

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


if __name__ == "__main__":
    unittest.main()
