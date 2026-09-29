# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Check Stack 20 wrapper preparation without touching running services.

The wrapper is loaded as a Python entrypoint. Tests use
temporary locks and mocked subprocess calls to verify noninteractive package
invocation, safe lock behavior, and failure propagation without Docker.
"""

import importlib.machinery
import importlib.util
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True

import pytest

from tests.helpers import ROOT


def load_wrapper():
    """Load the Stack 20 wrapper without executing its CLI."""
    path = ROOT / "wrapper/bin/stack-20.py"
    loader = importlib.machinery.SourceFileLoader("stack_20_wrapper_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_existing_lock_reports_status_without_running_prepare(tmp_path, monkeypatch, capsys):
    """Leave a prepared stack untouched and print the manual start command."""
    wrapper = load_wrapper()
    lock = tmp_path / ".lock"
    lock.write_text("prepared")
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 0
    output = capsys.readouterr().out
    assert "Removing .lock manually" in output
    assert "docker compose --env-file .env -f docker-compose.yml up -d" in output


def test_missing_lock_runs_package_and_requires_new_lock(tmp_path, monkeypatch, capsys):
    """Invoke preparation as a package with closed stdin and validate its lock."""
    wrapper = load_wrapper()
    lock = tmp_path / ".lock"
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    calls = []

    def fake_run(command, **kwargs):
        """Simulate successful preparation while capturing subprocess options."""
        calls.append((command, kwargs))
        lock.write_text("prepared")
        return SimpleNamespace(returncode=0, stdout="prepared\n", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    assert wrapper.main(["install"]) == 0
    command, options = calls[0]
    assert command == [sys.executable, "-B", "-m", wrapper.PREPARE_MODULE]
    assert options["stdin"] == wrapper.subprocess.DEVNULL
    assert options["cwd"] == tmp_path
    assert str(ROOT) in options["env"]["PYTHONPATH"].split(wrapper.os.pathsep)
    assert "prepared\n" in capsys.readouterr().out


def test_failed_prepare_does_not_claim_ready(tmp_path, monkeypatch, capsys):
    """Preserve a nonzero exit code and withhold deployment instructions."""
    wrapper = load_wrapper()
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=3, stdout="", stderr="missing Stack 0\n"
    ))

    assert wrapper.main(["install"]) == 3
    captured = capsys.readouterr()
    assert "missing Stack 0" in captured.err
    assert "docker compose" not in captured.out


def test_symlink_lock_is_rejected(tmp_path, monkeypatch):
    """Avoid calling preparation when .lock redirects to another file."""
    wrapper = load_wrapper()
    target = tmp_path / "target"
    target.write_text("prepared")
    lock = tmp_path / ".lock"
    lock.symlink_to(target)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 1
