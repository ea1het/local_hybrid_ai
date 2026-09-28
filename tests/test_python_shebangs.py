"""Checks for the executable Python shebang policy."""

import sys

sys.dont_write_bytecode = True

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from tests.helpers import ROOT


SCRIPT = ROOT / ".github/workflows/gha_apply_python_shebangs.py"


def load_script():
    spec = importlib.util.spec_from_file_location("gha_apply_python_shebangs_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_selects_only_executable_tracked_python(monkeypatch, tmp_path):
    module = load_script()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    entries = (
        b"100755 abc 0\tstack/prepare.py\0"
        b"100644 abc 0\tstack/helper.py\0"
        b"120000 abc 0\tstack/link.py\0"
        b"100755 abc 0\tstack/entrypoint.sh\0"
    )
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(stdout=entries))
    assert module.git_executable_python_files() == [tmp_path / "stack/prepare.py"]


def test_check_and_apply_only_required_shebangs(monkeypatch, tmp_path, capsys):
    module = load_script()
    executable = tmp_path / "prepare.py"
    executable.write_text("print('ready')\n")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "git_executable_python_files", lambda: [executable])
    assert module.scan(True) == 1
    assert executable.read_text() == "print('ready')\n"
    assert module.scan(False) == 0
    assert executable.read_text().startswith(module.SHEBANG)
    assert module.scan(True) == 0
    assert "passed" in capsys.readouterr().out


def test_preserves_incompatible_or_unsafe_files(monkeypatch, tmp_path):
    module = load_script()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    target = tmp_path / "target.py"
    target.write_text("print('untouched')\n")
    link = tmp_path / "link.py"
    link.symlink_to(target)
    other = tmp_path / "python2.py"
    other.write_text("#!/usr/bin/env python2\nprint('old')\n")
    bom = tmp_path / "bom.py"
    bom.write_text("\ufeffprint('bom')\n")
    monkeypatch.setattr(module, "git_executable_python_files", lambda: [link, other, bom])
    assert module.scan(False) == 1
    assert target.read_text() == "print('untouched')\n"
    assert other.read_text().startswith("#!/usr/bin/env python2")
    assert bom.read_text().startswith("\ufeff")
