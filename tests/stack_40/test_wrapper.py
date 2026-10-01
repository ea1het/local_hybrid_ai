# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Check that Stack 40 initializes Gitea without starting services.

The tests load the Python wrapper with a temporary lock and mocked
subprocess results. They verify package invocation, safety around an
existing lock, and failure propagation without contacting Docker or Gitea.
"""

import importlib.machinery
import importlib.util
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True

import pytest

from tests.helpers import ROOT


def load_wrapper():
    """Load the Stack 40 entrypoint without invoking its main function."""
    path = ROOT / "wrapper/bin/stack-40.py"
    loader = importlib.machinery.SourceFileLoader("stack_40_wrapper_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_existing_lock_is_explained_without_running_prepare(tmp_path, monkeypatch, capsys):
    """Preserve a locked stack and show the separate deployment step."""
    wrapper = load_wrapper()
    lock = tmp_path / ".lock"
    lock.write_text("prepared")
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 0
    output = capsys.readouterr().out
    assert "Removing .lock manually" in output
    assert "\n\nStack 40 is INSTALLED" in output
    assert "./local-ai stack-40 start" in output


def test_missing_lock_prepares_and_initializes_admin(tmp_path, monkeypatch, capsys):
    """Invoke both phases with closed stdin, then create .lock."""
    wrapper = load_wrapper()
    platform = tmp_path / "stack-00_-_platform"
    platform.mkdir()
    (platform / ".lock").touch()
    lock = tmp_path / ".lock"
    monkeypatch.setattr(wrapper, "ROOT", tmp_path)
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    calls = []

    def fake_run(command, **kwargs):
        """Simulate preparation and one-off administrator initialization."""
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="prepared\n", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    assert wrapper.main(["install"]) == 0
    assert calls[0][0] == [sys.executable, "-B", str(platform / "00-bootstrap.py"), "--stack", "40"]
    command, options = calls[1]
    assert command == [sys.executable, "-B", "-m", wrapper.PREPARE_MODULE]
    assert options["stdin"] == wrapper.subprocess.DEVNULL
    assert options["cwd"] == tmp_path
    assert str(tmp_path) in options["env"]["PYTHONPATH"].split(wrapper.os.pathsep)
    assert calls[2][0] == [sys.executable, "-B", "-m", wrapper.INITIALIZE_MODULE]
    assert lock.is_file()
    assert "Stack 40 is INSTALLED" in capsys.readouterr().out


def test_prepare_failure_does_not_claim_deployment(tmp_path, monkeypatch, capsys):
    """Forward failures and omit the manual deployment command."""
    wrapper = load_wrapper()
    platform = tmp_path / "stack-00_-_platform"
    platform.mkdir()
    (platform / ".lock").touch()
    monkeypatch.setattr(wrapper, "ROOT", tmp_path)
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda command, **kwargs: SimpleNamespace(
        returncode=5 if "-m" in command else 0, stdout="", stderr="missing source\n"
    ))

    assert wrapper.main(["install"]) == 5
    captured = capsys.readouterr()
    assert "missing source" in captured.err
    assert not (tmp_path / ".lock").exists()


def test_missing_platform_lock_stops_before_bootstrap(tmp_path, monkeypatch):
    """Do not create Gitea directories before the platform is prepared."""
    wrapper = load_wrapper()
    monkeypatch.setattr(wrapper, "ROOT", tmp_path)
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 1


def test_symlink_lock_is_rejected(tmp_path, monkeypatch):
    """Do not follow a lock symlink or call the preparation module."""
    wrapper = load_wrapper()
    target = tmp_path / "target"
    target.write_text("prepared")
    lock = tmp_path / ".lock"
    lock.symlink_to(target)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 1
