# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Test the Stack 60 wrapper without touching Hermes runtime state.

The Python entrypoint is loaded without running its CLI. Temporary
locks and mocked subprocess calls verify package invocation, lock safety,
failure propagation, and exclusion of optional Hermes operations.
"""

import importlib.machinery
import importlib.util
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True

import pytest

from tests.helpers import ROOT


def load_wrapper():
    """Load the Stack 60 wrapper without invoking its main function."""
    path = ROOT / "wrapper/bin/stack-60.py"
    loader = importlib.machinery.SourceFileLoader("stack_60_wrapper_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_existing_lock_skips_preparation_and_optional_actions(tmp_path, monkeypatch, capsys):
    """Preserve a locked runtime and show only manual deployment guidance."""
    wrapper = load_wrapper()
    lock = tmp_path / ".lock"
    lock.write_text("prepared")
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 0
    output = capsys.readouterr().out
    assert "Removing .lock manually" in output
    assert "docker compose --env-file .env -f docker-compose.yml up -d --build" in output
    assert "cleanup are separate operations" in output


def test_missing_lock_calls_only_prepare_package(tmp_path, monkeypatch, capsys):
    """Run Hermes preparation with closed stdin and validate its lock."""
    wrapper = load_wrapper()
    lock = tmp_path / ".lock"
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    calls = []

    def fake_run(command, **kwargs):
        """Capture the single preparation call and simulate audit success."""
        calls.append((command, kwargs))
        lock.write_text("prepared")
        return SimpleNamespace(returncode=0, stdout="audit passed\n", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    assert wrapper.main(["install"]) == 0
    command, options = calls[0]
    assert command == [sys.executable, "-B", "-m", wrapper.PREPARE_MODULE]
    assert options["stdin"] == wrapper.subprocess.DEVNULL
    assert options["cwd"] == tmp_path
    assert str(ROOT) in options["env"]["PYTHONPATH"].split(wrapper.os.pathsep)
    assert "audit passed\n" in capsys.readouterr().out


def test_prepare_failure_does_not_claim_hermes_ready(tmp_path, monkeypatch, capsys):
    """Preserve a failing exit code without printing startup instructions."""
    wrapper = load_wrapper()
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=8, stdout="", stderr="audit failed\n"
    ))

    assert wrapper.main(["install"]) == 8
    captured = capsys.readouterr()
    assert "audit failed" in captured.err
    assert "docker compose" not in captured.out


def test_symlink_lock_is_rejected_without_execution(tmp_path, monkeypatch):
    """Refuse a redirected preparation lock before calling the stack module."""
    wrapper = load_wrapper()
    target = tmp_path / "target"
    target.write_text("prepared")
    lock = tmp_path / ".lock"
    lock.symlink_to(target)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 1
