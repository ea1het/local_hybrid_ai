# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Exercise stack-owned reconfiguration without changing real containers."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import sqlite3
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
    monkeypatch.setattr(module, "managed_needs_update", lambda source, target: True)
    changed = []
    monkeypatch.setattr(module, "sync_managed", lambda source, target: changed.append(target.name) or True)
    if files[0] == "haproxy.cfg":
        config = base / "service_-_haproxy/config"
        config.mkdir(parents=True)
        (config / "tls.crt").write_text("cert")
        (config / "tls.key").write_text("key")
    assert module.main(True) == 0
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


def test_file_stack_preview_does_not_write(tmp_path, monkeypatch, capsys):
    """A bare reconfig shows the plan but never copies or backs up files."""
    module = load_module("stack-20_-_searxng_firecrawl", "reconfig.py")
    monkeypatch.setattr(module, "environment", lambda _: {"BASE_PATH": str(tmp_path)})
    monkeypatch.setattr(module, "compose_config", lambda _: None)
    monkeypatch.setattr(module, "managed_needs_update", lambda *args: True)
    monkeypatch.setattr(module, "sync_managed", lambda *args: pytest.fail("preview must not write"))
    assert module.main() == 0
    assert "Preview only" in capsys.readouterr().out


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
    assert module.main(True) == 0
    assert b"default: router" in captured[0]
    assert b"disabled_toolsets: []" in captured[0]


def test_hermes_preview_does_not_rewrite_runtime(tmp_path, monkeypatch, capsys):
    """Detected model and override drift remains read-only by default."""
    module = load_module("stack-60_-_hermes", "reconfig.py")
    config = tmp_path / "service_-_hermes/config/config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("disabled_toolsets: [web]\n")
    monkeypatch.setattr(module, "environment", lambda _: {
        "BASE_PATH": str(tmp_path), "HERMES_SERVICE": "service_-_hermes", "HERMES_MODEL": "router",
    })
    monkeypatch.setattr(module, "compose_config", lambda _: None)
    monkeypatch.setattr(module, "needs_update", lambda *args: True)
    monkeypatch.setattr(module, "sync_content", lambda *args: pytest.fail("preview must not write"))
    monkeypatch.setattr(module, "reconcile", lambda *args: pytest.fail("preview must not remove overrides"))
    assert module.main() == 0
    assert "runtime overrides remove" in capsys.readouterr().out


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
    assert module.main(True) == 1
    assert "./local-ai stack-70 stop" in capsys.readouterr().out


def test_webui_preview_with_stale_key_is_read_only(tmp_path, monkeypatch):
    """A running WebUI only reports its stale key until --apply is requested."""
    module = load_module("stack-70_-_open-webui", "reconfig.py")
    monkeypatch.setattr(module, "environment", lambda _: {
        "BASE_PATH": str(tmp_path), "OPENWEBUI_LITELLM_BASE_URL": "http://litellm:4000/v1",
        "OPENWEBUI_LITELLM_API_KEY": "sk-new",
    })
    monkeypatch.setattr(module, "container_running", lambda _: True)
    monkeypatch.setattr(module, "needs_update", lambda *args: True)
    monkeypatch.setattr(module, "reconcile", lambda *args: pytest.fail("preview must not write"))
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: pytest.fail("no policy mutation"))
    assert module.main() == 0


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
    assert module.main(True) == 0
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
    assert module.main(True) == 0
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


def gitea_fixture(tmp_path, monkeypatch):
    """Prepare only the managed paths needed for Stack 40 reconciliation."""
    module = load_module("stack-40_-_gitea", "reconfig.py")
    service = tmp_path / "service_-_gitea"
    app = service / "config/app.ini"
    alias = service / "config/conf/app.ini"
    runner = tmp_path / "service_-_gitea-runner/data/config.yaml"
    app.parent.mkdir(parents=True)
    alias.parent.mkdir()
    alias.symlink_to("../app.ini")
    runner.parent.mkdir(parents=True)
    app.write_text("old")
    runner.write_text("old")
    values = {
        "BASE_PATH": str(tmp_path), "GITEA_DOCKER_NETWORK": "redlocal", "NETWORK_NAME": "redlocal",
        "GITEA_DOMAIN": "git.example.test", "GITEA_ROOT_URL": "https://git.example.test/",
        "GITEA_SSH_DOMAIN": "git.example.test", "GITEA_SSH_PORT": "2222",
        "GITEA_INTERNAL_TOKEN": "internal-secret", "GITEA_JWT_SECRET": "jwt-secret",
        "GITEA_ADMIN_USERNAME": "admin", "GITEA_ADMIN_PASSWORD": "new-secret",
        "GITEA_CONTAINER_NAME": "gitea",
    }
    monkeypatch.setattr(module, "environment", lambda _: values)
    monkeypatch.setattr(module, "compose_config", lambda _: None)
    monkeypatch.setattr(module, "validate_managed", lambda *args: None)
    monkeypatch.setattr(module, "render", lambda *args: b"rendered")
    return module, values


def test_gitea_reconfig_rotates_only_when_running(tmp_path, monkeypatch):
    """A stale admin password must not start Gitea implicitly."""
    module, _ = gitea_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "saved_fingerprint", lambda _: None)
    monkeypatch.setattr(module, "container_running", lambda _: False)
    monkeypatch.setattr(module, "backup_database", lambda _: pytest.fail("must not back up"))
    monkeypatch.setattr(module, "rotate_password", lambda *args: pytest.fail("must not rotate"))
    assert module.main(True) == 1


def test_gitea_reconfig_rotates_and_stages_without_lifecycle(tmp_path, monkeypatch):
    """Rotate via the existing container, then stage only managed files."""
    module, values = gitea_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "saved_fingerprint", lambda _: None)
    monkeypatch.setattr(module, "container_running", lambda _: True)
    calls = []
    monkeypatch.setattr(module, "backup_database", lambda path: calls.append(("backup", path)))
    monkeypatch.setattr(module, "rotate_password", lambda *args: calls.append(("rotate", args)))
    monkeypatch.setattr(module, "save_fingerprint", lambda *args: calls.append(("save", args)))
    monkeypatch.setattr(module, "sync_content", lambda content, path: calls.append(("stage", path)) or True)
    assert module.main(True) == 0
    assert [name for name, _ in calls] == ["backup", "rotate", "save", "stage", "stage"]
    assert calls[1][1] == ("gitea", "admin", values["GITEA_ADMIN_PASSWORD"])


def test_gitea_password_transport_uses_stdin_not_argv(monkeypatch):
    """Keep the secret out of the host process command line."""
    module = load_module("stack-40_-_gitea", "reconfig.py")
    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda command, **kwargs: (
        calls.append((command, kwargs)) or SimpleNamespace(returncode=0)
    ))
    module.rotate_password("gitea", "admin", "supersecret")
    command, kwargs = calls[0]
    assert command[:3] == ["docker", "exec", "-i"]
    assert "supersecret" not in " ".join(command)
    assert "supersecret" in kwargs["input"]


def test_gitea_preview_never_backs_up_or_rotates(tmp_path, monkeypatch, capsys):
    """A password difference is displayed, not applied, without --apply."""
    module, _ = gitea_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "saved_fingerprint", lambda _: None)
    monkeypatch.setattr(module, "container_running", lambda _: pytest.fail("preview need not inspect Gitea"))
    monkeypatch.setattr(module, "backup_database", lambda _: pytest.fail("preview must not back up"))
    monkeypatch.setattr(module, "rotate_password", lambda *args: pytest.fail("preview must not rotate"))
    monkeypatch.setattr(module, "sync_content", lambda *args: pytest.fail("preview must not stage"))
    assert module.main() == 0
    output = capsys.readouterr().out
    assert "password rotate" in output
    assert "new-secret" not in output


def test_gitea_password_fingerprint_is_keyed_and_secret_free():
    """Do not persist the plaintext or an unkeyed password digest."""
    module = load_module("stack-40_-_gitea", "reconfig.py")
    values = {"GITEA_ADMIN_USERNAME": "admin", "GITEA_ADMIN_PASSWORD": "secret",
              "GITEA_INTERNAL_TOKEN": "key-one"}
    first = module.fingerprint(values)
    assert "secret" not in first
    assert len(first) == 64
    values["GITEA_INTERNAL_TOKEN"] = "key-two"
    assert module.fingerprint(values) != first


def test_gitea_sqlite_backup_is_consistent_and_private(tmp_path):
    """Take a restorable database backup before credential rotation."""
    module = load_module("stack-40_-_gitea", "reconfig.py")
    database = tmp_path / "gitea.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE users (name TEXT)")
        connection.execute("INSERT INTO users VALUES ('admin')")
    backup = module.backup_database(database)
    assert backup.stat().st_mode & 0o077 == 0
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT name FROM users").fetchone() == ("admin",)


@pytest.mark.parametrize("number", ("00", "10", "20", "30", "40", "50", "60", "70"))
def test_wrapper_reconfig_only_delegates(number, monkeypatch):
    """The wrapper owns no stack-specific reconfiguration behavior."""
    import importlib.util
    from tests.helpers import ROOT

    path = ROOT / "wrapper/bin" / f"stack-{number}.py"
    spec = importlib.util.spec_from_file_location(f"reconfig_wrapper_{number}", path)
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    called = []
    from wrapper.lib import reconfig_dispatch
    monkeypatch.setattr(reconfig_dispatch, "run_reconfig", lambda stack_dir, apply=False: (
        called.append((stack_dir, apply)) or 0
    ))
    assert wrapper.main(["reconfig"]) == 0
    assert wrapper.main(["reconfig", "--apply"]) == 0
    assert called == [(wrapper.STACK_DIR, False), (wrapper.STACK_DIR, True)]


def test_dispatch_forwards_apply_only_when_explicit(tmp_path, monkeypatch):
    """The wrapper never turns a preview into an application implicitly."""
    from wrapper.lib import reconfig_dispatch

    module = tmp_path / "reconfig.py"
    module.write_text('"""Test module."""\n')
    commands = []
    monkeypatch.setattr(reconfig_dispatch, "run_with_progress", lambda label, command, **kwargs: (
        commands.append(command) or SimpleNamespace(returncode=0, stdout="", stderr="")
    ))
    assert reconfig_dispatch.run_reconfig(tmp_path) == 0
    assert reconfig_dispatch.run_reconfig(tmp_path, apply=True) == 0
    assert commands[0][-1] == str(module)
    assert commands[1][-2:] == [str(module), "--apply"]
