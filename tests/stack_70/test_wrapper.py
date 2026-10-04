# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Test the Stack 70 wrapper without issuing credentials or starting services.

These tests load the Python CLI entrypoint and replace its subprocess
calls. They verify lock safety, bootstrap-before-prepare ordering, failure
handling, and manual-only startup instructions.
"""

import importlib.machinery
import importlib.util
import json
import sqlite3
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True

import pytest

from tests.helpers import ROOT


def load_wrapper():
    """Load the Stack 70 CLI without executing its main function."""
    path = ROOT / "wrapper/bin/stack-70.py"
    loader = importlib.machinery.SourceFileLoader("stack_70_wrapper_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def prepare_prerequisite_locks(root):
    """Create the two installation prerequisites in an isolated worktree."""
    for name in ("stack-00_-_platform", "stack-30_-_litellm"):
        stack = root / name
        stack.mkdir()
        (stack / ".lock").touch()


def test_existing_lock_skips_bootstrap_and_prepare(tmp_path, monkeypatch, capsys):
    """Leave credentials untouched when preparation was already recorded."""
    wrapper = load_wrapper()
    lock = tmp_path / ".lock"
    lock.write_text("prepared")
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 0
    output = capsys.readouterr().out
    assert "bootstrap and prepare were not run" in output
    assert "./local-ai stack-70 reconfig" in output
    assert "\n\nStack 70 is PREPARED" in output
    assert "./local-ai stack-70 start" in output


def test_fresh_stack_bootstraps_then_prepares(tmp_path, monkeypatch, capsys):
    """Create directories before the two package modules and validate the lock."""
    wrapper = load_wrapper()
    prepare_prerequisite_locks(tmp_path)
    lock = tmp_path / ".lock"
    monkeypatch.setattr(wrapper, "ROOT", tmp_path)
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    calls = []

    def fake_run(command, **kwargs):
        """Record calls and simulate a successful preparation lock."""
        calls.append((command, kwargs))
        if command[-1] == wrapper.PREPARE_MODULE:
            lock.write_text("prepared")
        return SimpleNamespace(returncode=0, stdout="audit passed\n", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    assert wrapper.main(["install"]) == 0
    assert [call[0] for call in calls] == [
        [sys.executable, "-B", str(tmp_path / "stack-00_-_platform" / "00-bootstrap.py"), "--stack", "70"],
        [sys.executable, "-B", "-m", wrapper.BOOTSTRAP_MODULE],
        [sys.executable, "-B", "-m", wrapper.PREPARE_MODULE],
    ]
    assert all(options["stdin"] == wrapper.subprocess.DEVNULL for _, options in calls)
    assert all(options["cwd"] == tmp_path for _, options in calls)
    assert str(tmp_path) in calls[0][1]["env"]["PYTHONPATH"].split(wrapper.os.pathsep)
    assert "audit passed\n\nStack 70 is PREPARED" in capsys.readouterr().out


@pytest.mark.parametrize("failed_module", ["directories", "bootstrap", "prepare"])
def test_failure_stops_without_startup_guidance(tmp_path, monkeypatch, capsys, failed_module):
    """Propagate a failed phase and never claim that preparation completed."""
    wrapper = load_wrapper()
    prepare_prerequisite_locks(tmp_path)
    monkeypatch.setattr(wrapper, "ROOT", tmp_path)
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    calls = []

    def fake_run(command, **kwargs):
        """Fail at the selected package module and record invocation order."""
        calls.append(command[-1])
        failed = (failed_module == "directories" and command[-1] == "70") or (
            failed_module == "bootstrap" and command[-1] == wrapper.BOOTSTRAP_MODULE
        ) or (failed_module == "prepare" and command[-1] == wrapper.PREPARE_MODULE)
        return SimpleNamespace(returncode=7 if failed else 0, stdout="", stderr="audit failed\n" if failed else "")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    assert wrapper.main(["install"]) == 7
    assert len(calls) == {"directories": 1, "bootstrap": 2, "prepare": 3}[failed_module]
    captured = capsys.readouterr()
    assert "audit failed" in captured.err
    assert "docker compose" not in captured.out


def test_missing_prerequisite_lock_stops_before_bootstrap(tmp_path, monkeypatch):
    """Avoid filesystem or environment changes without Stack 00 and Stack 30."""
    wrapper = load_wrapper()
    monkeypatch.setattr(wrapper, "ROOT", tmp_path)
    monkeypatch.setattr(wrapper, "STACK_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 1


def test_symlink_lock_is_rejected(tmp_path, monkeypatch):
    """Reject a redirected lock before invoking either module."""
    wrapper = load_wrapper()
    target = tmp_path / "target"
    target.write_text("prepared")
    lock = tmp_path / ".lock"
    lock.symlink_to(target)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))

    assert wrapper.main(["install"]) == 1


def test_start_updates_only_stale_litellm_key_before_compose(tmp_path, monkeypatch):
    """Stop a running WebUI before rotating its SQLite key, then start it."""
    wrapper = load_wrapper()
    stack_dir = tmp_path / "stack-70_-_open-webui"
    stack_dir.mkdir()
    (stack_dir / ".env").symlink_to("../.env")
    (tmp_path / ".env").write_text("protected\n")
    (stack_dir / "docker-compose.yml").touch()
    lock = stack_dir / ".lock"
    lock.touch()
    data = tmp_path / "runtime/service_-_open-webui/data"
    data.mkdir(parents=True)
    database = data / "webui.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value JSON NOT NULL, updated_at BIGINT)")
        for name, value in (("openai.api_base_urls", ["http://litellm:4000/v1"]),
                            ("openai.api_keys", ["old"]), ("web.search", {"enabled": True})):
            connection.execute("INSERT INTO config VALUES (?, ?, 0)", (name, json.dumps(value)))
    monkeypatch.setattr(wrapper, "ROOT", tmp_path)
    monkeypatch.setattr(wrapper, "STACK_DIR", stack_dir)
    monkeypatch.setattr(wrapper, "LOCK_FILE", lock)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper, "protected_text", lambda _: (
        f"BASE_PATH={tmp_path / 'runtime'}\nOPENWEBUI_LITELLM_BASE_URL=http://litellm:4000/v1\n"
        "OPENWEBUI_LITELLM_API_KEY=new\n"))
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["docker", "ps"]:
            return SimpleNamespace(returncode=0, stdout="open-webui running\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    monkeypatch.setattr(wrapper, "run_with_progress", lambda label, command, **kwargs: fake_run(command, **kwargs))
    assert wrapper.run_compose("up") == 0
    assert any(command[-2:] == ["stop", "open-webui"] for command in calls)
    assert calls[-1][-2:] == ["up", "-d"]
    with sqlite3.connect(database) as connection:
        assert json.loads(connection.execute("SELECT value FROM config WHERE key='openai.api_keys'").fetchone()[0]) == ["new"]
        assert json.loads(connection.execute("SELECT value FROM config WHERE key='web.search'").fetchone()[0]) == {
            "enabled": True}
