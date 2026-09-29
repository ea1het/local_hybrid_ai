# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Test Stack 00's external reconciler without modifying host resources.

The Python entrypoint is loaded without running it. Mocked install
calls verify that a lock does not bypass the audit, failures propagate, and
the wrapper never starts application containers itself.
"""

import importlib.machinery
import importlib.util
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True

import pytest

from tests.helpers import ROOT


def load_wrapper():
    """Load the Stack 00 CLI without executing its main function."""
    path = ROOT / "wrapper/bin/stack-00.py"
    loader = importlib.machinery.SourceFileLoader("stack_00_wrapper_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.mark.parametrize("already_locked", [False, True])
def test_wrapper_runs_installer_regardless_of_lock(tmp_path, monkeypatch, capsys, already_locked):
    """Run one complete audit and demand a lock on success."""
    wrapper = load_wrapper()
    lock = tmp_path / ".lock"
    if already_locked:
        lock.write_text("prepared")
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    calls = []

    def fake_run(command, **kwargs):
        """Record the package call and simulate successful lock creation."""
        calls.append((command, kwargs))
        if not lock.exists():
            lock.write_text("prepared")
        return SimpleNamespace(returncode=0, stdout="audit passed\n", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    assert wrapper.main(["install"]) == 0
    assert calls[0][0] == [sys.executable, "-B", "-m", wrapper.INSTALL_MODULE]
    assert calls[0][1]["stdin"] == wrapper.subprocess.DEVNULL
    assert calls[0][1]["cwd"] == tmp_path
    assert str(ROOT) in calls[0][1]["env"]["PYTHONPATH"].split(wrapper.os.pathsep)
    assert "no application containers were started" in capsys.readouterr().out


def test_wrapper_failure_does_not_claim_prepared(tmp_path, monkeypatch, capsys):
    """Propagate the audit error without fabricating a lock."""
    wrapper = load_wrapper()
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=5, stdout="", stderr="verification failed\n"
    ))

    assert wrapper.main(["install"]) == 5
    output = capsys.readouterr()
    assert "verification failed" in output.err
    assert "PREPARED" not in output.out


def test_wrapper_rejects_symlink_lock(tmp_path, monkeypatch):
    """Reject an unsafe lock path before starting any phase."""
    wrapper = load_wrapper()
    target = tmp_path / "target"
    target.write_text("prepared")
    lock = tmp_path / ".lock"
    lock.symlink_to(target)
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 1
