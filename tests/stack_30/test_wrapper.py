# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Test the Stack 30 install sequence without provisioning real services.

Temporary locks and mocked subprocess calls exercise the Python
wrapper's lock handling, package invocation, and failure reporting.
The tests never contact PostgreSQL or Docker.
"""

import importlib.machinery
import importlib.util
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True

import pytest

from tests.helpers import ROOT


def load_wrapper():
    """Load the Stack 30 wrapper without running its CLI."""
    path = ROOT / "wrapper/bin/stack-30.py"
    loader = importlib.machinery.SourceFileLoader("stack_30_wrapper_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_existing_lock_prevents_prepare_and_describes_next_steps(tmp_path, monkeypatch, capsys):
    """Leave existing configuration untouched and avoid provisioning."""
    wrapper = load_wrapper()
    lock = tmp_path / ".lock"
    lock.write_text("prepared")
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 0
    output = capsys.readouterr().out
    assert "Removing .lock manually" in output
    assert "\n\nStack 30 is INSTALLED" in output
    assert "./local-ai stack-30 start" in output


def test_missing_lock_runs_all_install_phases(tmp_path, monkeypatch, capsys):
    """Provision and issue keys before creating the installation lock."""
    wrapper = load_wrapper()
    lock = tmp_path / ".lock"
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    calls = []

    def fake_run(command, **kwargs):
        """Record each subprocess without creating the lock on its behalf."""
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="prepared\n" if command[0] == sys.executable else "", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    assert wrapper.main(["install"]) == 0
    command, options = calls[1]
    assert command == [sys.executable, "-B", "-m", wrapper.PREPARE_MODULE]
    assert options["stdin"] == wrapper.subprocess.DEVNULL
    assert options["cwd"] == tmp_path
    assert str(ROOT) in options["env"]["PYTHONPATH"].split(wrapper.os.pathsep)
    assert [command[3] for command, _ in calls if command[0] == sys.executable] == [
        wrapper.PREPARE_MODULE, wrapper.PROVISION_MODULE, wrapper.KEYS_MODULE]
    assert lock.is_file()
    assert "Stack 30 is INSTALLED" in capsys.readouterr().out


def test_failed_prepare_does_not_claim_database_is_ready(tmp_path, monkeypatch, capsys):
    """Propagate failure without printing database or startup commands."""
    wrapper = load_wrapper()
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda command, **kwargs: SimpleNamespace(
        returncode=4 if command[0] == sys.executable else 0, stdout="", stderr="missing prerequisite\n"
    ))

    assert wrapper.main(["install"]) == 4
    captured = capsys.readouterr()
    assert "missing prerequisite" in captured.err
    assert not (tmp_path / ".lock").exists()


def test_symlink_lock_is_rejected_without_execution(tmp_path, monkeypatch):
    """Refuse symlinked locks rather than following a potentially unsafe path."""
    wrapper = load_wrapper()
    target = tmp_path / "target"
    target.write_text("prepared")
    lock = tmp_path / ".lock"
    lock.symlink_to(target)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 1
