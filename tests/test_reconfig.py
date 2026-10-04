"""Exercise stack-owned reconfiguration without changing real containers."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from types import SimpleNamespace

import pytest

from tests.helpers import load_module


def test_managed_files_are_staged_and_backed_up(tmp_path, monkeypatch):
    """An idempotent update keeps the previous runtime file in runtime."""
    from wrapper.lib import reconfig_runtime

    monkeypatch.setattr(reconfig_runtime.os, "chown", lambda *args: None)
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_text("new")
    target.write_text("old")
    assert reconfig_runtime.sync_managed(source, target)
    assert target.read_text() == "new"
    backups = list(tmp_path.glob("target-backup-*"))
    assert len(backups) == 1 and backups[0].read_text() == "old"
    assert not reconfig_runtime.sync_managed(source, target)
    assert len(list(tmp_path.glob("target-backup-*"))) == 1


@pytest.mark.parametrize("stack,files", [
    ("stack-10_-_haproxy_web", ("haproxy.cfg", "index.html")),
    ("stack-20_-_searxng_firecrawl", ("settings.yml", "limiter.toml", "favicons.toml")),
])
def test_file_stacks_only_stage_managed_files(stack, files, tmp_path, monkeypatch, capsys):
    """Neither file reconciler invokes container lifecycle operations."""
    module = load_module(stack, "reconfig.py")
    base = tmp_path / "runtime"
    base.mkdir()
    monkeypatch.setattr(module, "environment", lambda _: {"BASE_PATH": str(base)})
    monkeypatch.setattr(module, "compose_config", lambda _: None)
    monkeypatch.setattr(module, "validate_managed", lambda *args: None)
    changed = []
    monkeypatch.setattr(module, "sync_managed", lambda source, target: changed.append(target.name) or True)
    if files[0] == "haproxy.cfg":
        config = base / "service_-_haproxy/config"
        config.mkdir(parents=True)
        (config / "tls.crt").write_text("cert")
        (config / "tls.key").write_text("key")
    assert module.main() == 0
    assert tuple(changed) == files
    output = capsys.readouterr().out
    assert "./local-ai" in output
    assert "No containers were stopped or started" in output


def test_managed_file_validation_rejects_symlinks(tmp_path):
    """Do not overwrite an indirect runtime path or its referent."""
    from wrapper.lib import reconfig_runtime

    source = tmp_path / "source"
    source.write_text("managed")
    outside = tmp_path / "outside"
    outside.write_text("private")
    target = tmp_path / "target"
    target.symlink_to(outside)
    with pytest.raises(reconfig_runtime.ReconfigError, match="unsafe"):
        reconfig_runtime.validate_managed(source, target)
    assert outside.read_text() == "private"


def test_hermes_reconfig_preserves_web_state_and_never_restarts(tmp_path, monkeypatch):
    """Render the new model without changing the operator's web/Git intent."""
    module = load_module("stack-60_-_hermes", "reconfig.py")
    config = tmp_path / "service_-_hermes/config/config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("disabled_toolsets: []\n")
    values = {"BASE_PATH": str(tmp_path), "HERMES_SERVICE": "service_-_hermes", "HERMES_MODEL": "router"}
    monkeypatch.setattr(module, "environment", lambda _: values)
    monkeypatch.setattr(module, "compose_config", lambda _: None)
    captured = []
    monkeypatch.setattr(module, "sync_content", lambda content, path: captured.append(content) or True)
    monkeypatch.setattr(module, "reconcile", lambda path, keys: False)
    assert module.main() == 0
    assert b"default: router" in captured[0]
    assert b"disabled_toolsets: []" in captured[0]


def test_webui_running_with_stale_key_requests_manual_stop(tmp_path, monkeypatch, capsys):
    """Never write Open WebUI's SQLite database while the app is running."""
    module = load_module("stack-70_-_open-webui", "reconfig.py")
    monkeypatch.setattr(module, "environment", lambda _: {
        "BASE_PATH": str(tmp_path), "OPENWEBUI_LITELLM_BASE_URL": "http://litellm:4000/v1",
        "OPENWEBUI_LITELLM_API_KEY": "sk-new",
    })
    monkeypatch.setattr(module, "container_running", lambda _: True)
    monkeypatch.setattr(module, "needs_update", lambda *args: True)
    monkeypatch.setattr(module, "reconcile", lambda *args: pytest.fail("must not write a live database"))
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run policy"))
    assert module.main() == 1
    assert "./local-ai stack-70 stop" in capsys.readouterr().out


def test_webui_running_with_current_key_reconciles_policy(tmp_path, monkeypatch):
    """Only the already-running application's ORM policy script is invoked."""
    module = load_module("stack-70_-_open-webui", "reconfig.py")
    monkeypatch.setattr(module, "environment", lambda _: {
        "BASE_PATH": str(tmp_path), "OPENWEBUI_LITELLM_BASE_URL": "http://litellm:4000/v1",
        "OPENWEBUI_LITELLM_API_KEY": "sk-current",
    })
    monkeypatch.setattr(module, "container_running", lambda _: True)
    monkeypatch.setattr(module, "needs_update", lambda *args: False)
    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda command, **kwargs: (
        calls.append(command) or SimpleNamespace(returncode=0)
    ))
    assert module.main() == 0
    assert len(calls) == 1 and calls[0][-1].endswith("reconcile-model-policy.py")


def test_webui_stopped_updates_key_without_starting(tmp_path, monkeypatch, capsys):
    """Offline SQLite synchronization remains separate from model policy."""
    module = load_module("stack-70_-_open-webui", "reconfig.py")
    database = tmp_path / "service_-_open-webui/data/webui.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"fixture")
    monkeypatch.setattr(module, "environment", lambda _: {
        "BASE_PATH": str(tmp_path), "OPENWEBUI_LITELLM_BASE_URL": "http://litellm:4000/v1",
        "OPENWEBUI_LITELLM_API_KEY": "sk-new",
    })
    monkeypatch.setattr(module, "container_running", lambda _: False)
    monkeypatch.setattr(module, "needs_update", lambda *args: True)
    changed = []
    monkeypatch.setattr(module, "reconcile", lambda *args: changed.append(args) or True)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not use Docker"))
    assert module.main() == 0
    assert len(changed) == 1
    assert "./local-ai stack-70 start" in capsys.readouterr().out


def test_docker_inspection_failure_is_not_treated_as_stopped(monkeypatch):
    """An unavailable daemon must not authorize offline SQLite mutation."""
    from wrapper.lib import reconfig_runtime

    monkeypatch.setattr(reconfig_runtime.subprocess, "run", lambda *args, **kwargs: (
        SimpleNamespace(returncode=1, stdout="", stderr="Cannot connect to the Docker daemon")
    ))
    with pytest.raises(reconfig_runtime.ReconfigError, match="cannot inspect"):
        reconfig_runtime.container_running("open-webui")


@pytest.mark.parametrize("number", ("00", "10", "20", "30", "50", "60", "70"))
def test_wrapper_reconfig_only_delegates(number, monkeypatch):
    """The wrapper owns no stack-specific reconfiguration behavior."""
    import importlib.util
    from tests.helpers import ROOT

    path = ROOT / "wrapper/bin" / f"stack-{number}.py"
    spec = importlib.util.spec_from_file_location(f"reconfig_wrapper_{number}", path)
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    called = []
    monkeypatch.setattr(wrapper, "run_reconfig", lambda stack_dir: called.append(stack_dir) or 0)
    assert wrapper.main(["reconfig"]) == 0
    assert called == [wrapper.STACK_DIR]
