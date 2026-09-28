# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import sys

sys.dont_write_bytecode = True

from types import SimpleNamespace

import pytest

from tests.helpers import load_module


cleanup = load_module("stack-60_-_hermes", "cleanup.py")
reconcile = load_module("stack-60_-_hermes", "reconcile-capabilities.py")
workaround = load_module("stack-60_-_hermes", "apply-terminal-timeout-workaround.py")


def test_cleanup_rejects_managed_runtime_override(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("BASE_PATH=/runtime\nHERMES_MODEL=original\n")
    runtime = tmp_path / "data"
    runtime.mkdir()
    (runtime / ".env").write_text("HERMES_MODEL=override\n")
    monkeypatch.setattr(cleanup, "ENV_FILE", env_file)
    instance = object.__new__(cleanup.Cleanup)
    instance.hermes_data = runtime

    with pytest.raises(SystemExit, match="1"):
        instance.audit_runtime_env_safety()
    (runtime / ".env").write_text("TERMINAL_TIMEOUT=30\n")
    instance.audit_runtime_env_safety()


def test_cleanup_dry_run_preserves_files_and_rejects_escape(tmp_path, monkeypatch):
    root = tmp_path / "service_-_hermes"
    root.mkdir()
    target = root / "state.db"
    target.write_text("keep")
    outside = tmp_path / "outside"
    outside.write_text("keep")
    instance = object.__new__(cleanup.Cleanup)
    instance.hermes_root = root
    instance.sandbox_root = tmp_path / "service_-_sandbox"
    instance.dry_run = True
    monkeypatch.setattr(cleanup.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not remove"))

    instance.remove_path(target)
    assert target.read_text() == "keep"
    with pytest.raises(SystemExit, match="1"):
        instance.remove_path(outside)
    assert outside.read_text() == "keep"


def test_reconcile_config_toggles_web_only_when_available(tmp_path, monkeypatch):
    source = tmp_path / "config.yaml"
    source.write_text("model: ${HERMES_MODEL}\ndisabled_toolsets: [web]\n")
    monkeypatch.setattr(reconcile, "SOURCE_CONFIG", source)

    assert reconcile.render_config("local/model", False) == b"model: local/model\ndisabled_toolsets: [web]\n"
    assert reconcile.render_config("local/model", True) == b"model: local/model\ndisabled_toolsets: []\n"


def test_reconcile_state_defaults_disabled_and_rejects_invalid(tmp_path):
    state = tmp_path / "desired-state"
    assert reconcile.read_git_memory_state(state) == "disabled"
    state.write_text("enabled\n")
    assert reconcile.read_git_memory_state(state) == "enabled"
    state.write_text("unexpected\n")
    with pytest.raises(SystemExit, match="1"):
        reconcile.read_git_memory_state(state)


def test_reconcile_stops_only_running_memory_sidecar(monkeypatch):
    commands = []
    monkeypatch.setattr(reconcile, "container_running", lambda name: name == "sync")
    monkeypatch.setattr(reconcile, "run", lambda *args, **kwargs: commands.append(args))
    reconcile.stop_memory_sync_if_running("sync")
    reconcile.stop_memory_sync_if_running("stopped")
    assert commands == [("docker", "stop", "sync")]


def test_timeout_values_require_exact_assignment(tmp_path):
    path = tmp_path / ".env"
    path.write_text("TERMINAL_TIMEOUT=20\nexport TERMINAL_TIMEOUT=30\n# TERMINAL_TIMEOUT=40\nOTHER=50\n")
    assert workaround.timeout_values(path) == ["20", "30"]


def test_workaround_rejects_invalid_container_timeout_before_rewrite(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    env_file.touch()
    runtime = tmp_path / "service_-_hermes" / "data" / ".env"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("TERMINAL_TIMEOUT=20\n")
    monkeypatch.setattr(workaround, "ENV_FILE", env_file)
    monkeypatch.setattr(workaround.os, "geteuid", lambda: 0)
    monkeypatch.setattr(workaround, "load_env", lambda path: {
        "BASE_PATH": str(tmp_path), "HERMES_SERVICE": "service_-_hermes", "HERMES_CONTAINER": "hermes",
    })
    monkeypatch.setattr(workaround.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        return "true" if "{{.State.Running}}" in args else "0; rm -rf /"

    monkeypatch.setattr(workaround, "run", fake_run)
    with pytest.raises(SystemExit, match="1"):
        workaround.main()
    assert "Invalid TERMINAL_TIMEOUT" in capsys.readouterr().err
    assert runtime.read_text() == "TERMINAL_TIMEOUT=20\n"
    assert not any("restart" in command for command in calls)
