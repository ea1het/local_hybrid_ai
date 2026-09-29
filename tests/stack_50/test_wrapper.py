# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Test the Stack 50 preparation wrapper without Docker side effects.

These cases load the Python entrypoint and simulate volume-capable
preparation with mocked subprocess calls. They verify that a lock blocks
reconfiguration, failures propagate, and manual startup remains separate.
"""

import importlib.machinery
import importlib.util
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True

import pytest

from tests.helpers import ROOT


def load_wrapper():
    """Load the Stack 50 wrapper without running its command-line main."""
    path = ROOT / "wrapper/bin/stack-50.py"
    loader = importlib.machinery.SourceFileLoader("stack_50_wrapper_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_existing_lock_explains_state_without_running_prepare(tmp_path, monkeypatch, capsys):
    """Keep the locked stack untouched and print manual startup guidance."""
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


def test_missing_lock_calls_package_prepare_once(tmp_path, monkeypatch, capsys):
    """Run preparation without stdin and validate the new regular lock."""
    wrapper = load_wrapper()
    lock = tmp_path / ".lock"
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    calls = []

    def fake_run(command, **kwargs):
        """Capture the package command and simulate successful preparation."""
        calls.append((command, kwargs))
        lock.write_text("prepared")
        return SimpleNamespace(returncode=0, stdout="volume created\n", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    assert wrapper.main(["install"]) == 0
    command, options = calls[0]
    assert command == [sys.executable, "-B", "-m", wrapper.PREPARE_MODULE]
    assert options["stdin"] == wrapper.subprocess.DEVNULL
    assert options["cwd"] == tmp_path
    assert str(ROOT) in options["env"]["PYTHONPATH"].split(wrapper.os.pathsep)
    assert "volume created\n" in capsys.readouterr().out


def test_failed_prepare_does_not_claim_dockhand_started(tmp_path, monkeypatch, capsys):
    """Preserve a failure and suppress the manual startup command."""
    wrapper = load_wrapper()
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=6, stdout="", stderr="Docker unavailable\n"
    ))

    assert wrapper.main(["install"]) == 6
    captured = capsys.readouterr()
    assert "Docker unavailable" in captured.err
    assert "docker compose" not in captured.out


def test_symlink_lock_is_rejected(tmp_path, monkeypatch):
    """Reject a redirected lock without touching Docker or service state."""
    wrapper = load_wrapper()
    target = tmp_path / "target"
    target.write_text("prepared")
    lock = tmp_path / ".lock"
    lock.symlink_to(target)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 1
