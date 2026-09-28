# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Behavior checks for the repository MPL header tool."""

import sys

sys.dont_write_bytecode = True

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github/workflows/gha_apply_mpl_headers.py"


def load_script():
    """Load the MPL header tool as an isolated test module."""
    spec = importlib.util.spec_from_file_location("gha_apply_mpl_headers_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_supported_comments_and_true_exceptions():
    """Check supported comment styles and genuine header exceptions."""
    module = load_script()
    assert module.classify(ROOT / "program_configs/inference_server/caddy/Caddyfile", "site {}").style == "hash"
    assert module.classify(ROOT / "program_configs/workstations/opencode/opencode.jsonc", "{}").style == "slash"
    for filename in ("LICENSE", "Todo.json", "rootCA.pem", "litellm.key"):
        assert module.classify(ROOT / filename, "content").style is None


def test_check_requires_exact_exception_report(tmp_path, monkeypatch, capsys):
    """Require the generated exception report to match the file scan."""
    module = load_script()
    source = tmp_path / "source.py"
    source.write_text("print('hello')\n")
    json_file = tmp_path / "Todo.json"
    json_file.write_text("{}\n")
    report = tmp_path / "docs/license-header-exceptions.md"
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "REPORT", report)
    monkeypatch.setattr(module, "git_files", lambda: [source, json_file])

    assert module.scan(True) == 1
    assert "source.py" in capsys.readouterr().out
    assert module.scan(False) == 0
    assert source.read_text().startswith("# This Source Code Form")
    assert "Todo.json" in report.read_text()
    assert module.scan(True) == 0

    report.write_text(report.read_text() + "stale\n")
    assert module.scan(True) == 1
    assert "docs/license-header-exceptions.md" in capsys.readouterr().out


def test_refuses_symlinked_report_and_missing_tracked_file(tmp_path, monkeypatch):
    """Reject unsafe reports and missing tracked paths without modifying targets."""
    module = load_script()
    report = tmp_path / "docs/license-header-exceptions.md"
    report.parent.mkdir()
    target = tmp_path / "outside"
    target.write_text("do not change")
    report.symlink_to(target)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "REPORT", report)
    monkeypatch.setattr(module, "git_files", lambda: [tmp_path / "missing.py"])
    assert module.scan(False) == 1
    assert target.read_text() == "do not change"
    report.unlink()
    assert module.scan(False) == 1
    assert not report.exists()
