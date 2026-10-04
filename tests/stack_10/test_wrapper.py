# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Verify that the Stack 10 wrapper is noninteractive and respects .lock.

The tests load the Python entrypoint as a module and replace
host calls with temporary files and test doubles. They cover existing locks,
successful preparation, failed preparation, and suspicious lock types without
executing Docker or modifying an operational stack.
"""

import importlib.machinery
import importlib.util
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True

import pytest

from tests.helpers import ROOT


def load_wrapper():
    """Load the Python executable without invoking its main function."""
    path = ROOT / "wrapper/bin/stack-10.py"
    loader = importlib.machinery.SourceFileLoader("stack_10_wrapper_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_existing_lock_is_informational_only(tmp_path, monkeypatch, capsys):
    """Skip preparation and explain manual reconfiguration and startup."""
    wrapper = load_wrapper()
    lock = tmp_path / ".lock"
    lock.write_text("prepared")
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 0
    output = capsys.readouterr().out
    assert "No configuration was changed" in output
    assert "./local-ai stack-10 reconfig" in output
    assert "\n\nStack 10 is PREPARED" in output
    assert "./local-ai stack-10 start" in output


def test_missing_lock_runs_package_once_and_reports_start_command(tmp_path, monkeypatch, capsys):
    """Use Python module execution with closed stdin and require a new lock."""
    wrapper = load_wrapper()
    lock = tmp_path / ".lock"
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    calls = []

    def fake_run(command, **kwargs):
        """Capture the command and simulate successful stack preparation."""
        calls.append((command, kwargs))
        lock.write_text("prepared")
        return SimpleNamespace(returncode=0, stdout="prepared\n", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    assert wrapper.main(["install"]) == 0
    command, options = calls[0]
    assert command == [sys.executable, "-B", "-m", wrapper.PREPARE_MODULE]
    assert options["cwd"] == tmp_path
    assert options["stdin"] == wrapper.subprocess.DEVNULL
    assert options["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert str(ROOT) in options["env"]["PYTHONPATH"].split(wrapper.os.pathsep)
    assert "prepared\n\nStack 10 is PREPARED" in capsys.readouterr().out


def test_prepare_failure_does_not_claim_readiness(tmp_path, monkeypatch, capsys):
    """Preserve the preparation exit status and avoid startup instructions."""
    wrapper = load_wrapper()
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=7, stdout="", stderr="prerequisite missing\n"
    ))

    assert wrapper.main(["install"]) == 7
    captured = capsys.readouterr()
    assert "prerequisite missing" in captured.err
    assert "docker compose" not in captured.out


def test_success_without_lock_is_rejected(tmp_path, monkeypatch, capsys):
    """Do not report preparation complete if the script omits its lock."""
    wrapper = load_wrapper()
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout="", stderr=""
    ))

    assert wrapper.main(["install"]) == 1
    assert "without a regular .lock" in capsys.readouterr().err


def test_symlink_lock_is_rejected_without_execution(tmp_path, monkeypatch):
    """Refuse a lock symlink even when its target exists."""
    wrapper = load_wrapper()
    target = tmp_path / "target"
    target.write_text("prepared")
    lock = tmp_path / ".lock"
    lock.symlink_to(target)
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 1
