# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Test Open WebUI bootstrap, preparation, and model-policy wrappers.

Cases use temporary environment files and mocked container calls to verify
secret preservation, readiness, and policy-script wiring. They never
issue LiteLLM keys or modify Open WebUI. Importing this module only
defines tests."""

import sys

sys.dont_write_bytecode = True

import re
import stat
from datetime import datetime
from types import SimpleNamespace

import pytest

from tests.helpers import load_module


STACK = "stack-70_-_open-webui"


def test_bootstrap_updates_only_missing_values_and_keeps_secrets_private(tmp_path, monkeypatch, capsys):
    """Fill missing settings without replacing custom values or printing secrets."""
    module = load_module(STACK, "00-bootstrap.py")
    env_file = tmp_path / ".env"
    env_file.write_text("OTHER=keep\nOPENWEBUI_IMAGE=custom/image\n"
                        "OPENWEBUI_LITELLM_API_KEY=PUT_YOUR_KEY_HERE\n")
    written = []
    backups = []
    monkeypatch.setattr(module, "ENV_FILE", env_file)
    monkeypatch.setattr(module, "require_env_file", lambda: env_file.read_text())
    monkeypatch.setattr(module.secrets, "token_hex", lambda _: "secret-private")
    monkeypatch.setattr(module, "backup_env", lambda original: backups.append(original) or tmp_path / "backup")
    monkeypatch.setattr(module, "atomic_write", lambda payload, original: written.append((payload, original)))

    assert module.main() == 0
    assert len(written) == 1
    assert backups == [env_file.read_text()]
    assert written[0][1] == backups[0]
    values, _ = module.parse_values(written[0][0])
    assert values["OPENWEBUI_IMAGE"] == "custom/image"
    assert values["OPENWEBUI_LITELLM_API_KEY"] == "PUT_YOUR_KEY_HERE"
    assert values["OPENWEBUI_SECRET_KEY"] == "secret-private"
    assert values["OPENWEBUI_VERSION"] == module.DEFAULTS["OPENWEBUI_VERSION"]
    assert "OTHER=keep" in written[0][0]
    output = capsys.readouterr().out
    assert "PUT_YOUR_KEY_HERE" not in output
    assert "secret-private" not in output


def test_bootstrap_backup_preserves_exact_bytes_and_rejects_collision(tmp_path, monkeypatch):
    """Write a protected timestamped backup without replacing an existing one."""
    module = load_module(STACK, "00-bootstrap.py")
    original = b"EXISTING=secret\r\n"
    env_file = tmp_path / ".env"
    env_file.write_bytes(original)
    env_file.chmod(0o600)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "ENV_FILE", env_file)
    monkeypatch.setattr(module.os, "fchown", lambda *args: None)
    actual_fstat = module.os.fstat
    monkeypatch.setattr(module.os, "fstat", lambda descriptor: SimpleNamespace(
        st_mode=actual_fstat(descriptor).st_mode, st_uid=0, st_gid=0
    ))

    class FixedDatetime(datetime):
        """Make the backup name deterministic for the collision check."""

        @classmethod
        def now(cls):
            """Return a fixed local timestamp."""
            return cls(2026, 9, 29, 2, 30, 45)

    monkeypatch.setattr(module, "datetime", FixedDatetime)
    backup = module.backup_env(original.decode())
    assert re.fullmatch(r"\.env-backup-\d{6}-\d{6}", backup.name)
    assert backup.read_bytes() == original
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        module.backup_env(original.decode())
    assert backup.read_bytes() == original


def test_bootstrap_backup_failure_prevents_changes(monkeypatch, capsys):
    """Fail before changing the environment when no safe backup can be made."""
    module = load_module(STACK, "00-bootstrap.py")
    monkeypatch.setattr(module, "require_env_file", lambda: "OPENWEBUI_LITELLM_API_KEY=PUT_YOUR_KEY_HERE\n")
    monkeypatch.setattr(module, "backup_env", lambda original: (_ for _ in ()).throw(
        module.BootstrapError("backup unavailable")
    ))

    assert module.main() == 1
    assert "backup unavailable" in capsys.readouterr().err


def test_bootstrap_rejects_duplicate_keys(monkeypatch, capsys):
    """Reject duplicate settings before changing the environment."""
    module = load_module(STACK, "00-bootstrap.py")
    monkeypatch.setattr(module, "require_env_file", lambda: "OPENWEBUI_IMAGE=a\nOPENWEBUI_IMAGE=b\n")
    assert module.main() == 1
    assert "duplicate Stack 70 variables" in capsys.readouterr().err


def test_prepare_validates_gateway_and_writes_lock(tmp_path, monkeypatch):
    """Validate the gateway and Compose config before writing the lock."""
    module = load_module(STACK, "01-prepare.py")
    stack_dir = tmp_path / STACK
    stack_dir.mkdir()
    central_env = tmp_path / ".env"
    central_env.touch()
    (stack_dir / ".env").symlink_to("../.env")
    (stack_dir / "docker-compose.yml").touch()
    for stack in ("stack-00_-_platform", "stack-30_-_litellm"):
        (tmp_path / stack).mkdir()
        (tmp_path / stack / ".lock").touch()
    data = tmp_path / "runtime/service_-_open-webui/data"
    data.mkdir(parents=True)
    env = {key: "configured" for key in module.REQUIRED_KEYS}
    env.update(STACKS_ROOT=str(tmp_path), BASE_PATH=str(tmp_path / "runtime"),
               NETWORK_NAME="internal", OPENWEBUI_VERSION="v0.11.3")
    commands = []

    def fake_run(command, **kwargs):
        """Record subprocess calls and report success."""
        commands.append(command)
        return SimpleNamespace(returncode=0)

    def fake_checked(*command, **kwargs):
        """Return Docker network and container state for preparation."""
        commands.append(command)
        if "{{.Driver}}" in command:
            return "bridge"
        if "{{.State.Running}}" in command:
            return "true"
        return ""

    monkeypatch.setattr(module, "STACK_DIR", stack_dir)
    monkeypatch.setattr(module, "ENV_FILE", stack_dir / ".env")
    monkeypatch.setattr(module, "COMPOSE_FILE", stack_dir / "docker-compose.yml")
    monkeypatch.setattr(module, "LOCK_FILE", stack_dir / ".lock")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.shutil, "which", lambda _: "/fake/docker")
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "run", fake_checked)
    monkeypatch.setattr(module, "load_env", lambda: env)

    module.main()

    assert any("{{.State.Running}}" in command for command in commands)
    assert any(command[-2:] == ("config", "--quiet") for command in commands)
    assert "stack=stack-70_-_open-webui" in (stack_dir / ".lock").read_text()


def test_prepare_rejects_placeholder_before_docker_inspect(tmp_path, monkeypatch):
    """Reject placeholder secrets before inspecting Docker state."""
    module = load_module(STACK, "01-prepare.py")
    stack_dir = tmp_path / STACK
    stack_dir.mkdir()
    (tmp_path / ".env").touch()
    (stack_dir / ".env").symlink_to("../.env")
    (stack_dir / "docker-compose.yml").touch()
    env = {key: "configured" for key in module.REQUIRED_KEYS}
    env["OPENWEBUI_SECRET_KEY"] = "PUT_YOUR_KEY_HERE"
    calls = []

    def fake_run(command, **kwargs):
        """Record subprocess calls and report success."""
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module, "STACK_DIR", stack_dir)
    monkeypatch.setattr(module, "ENV_FILE", stack_dir / ".env")
    monkeypatch.setattr(module, "COMPOSE_FILE", stack_dir / "docker-compose.yml")
    monkeypatch.setattr(module, "LOCK_FILE", stack_dir / ".lock")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.shutil, "which", lambda _: "/fake/docker")
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "load_env", lambda: env)
    with pytest.raises(module.PrepareError, match="still contains a placeholder"):
        module.main()
    assert calls == [("docker", "compose", "version")]


def test_wait_ready_retries_until_healthy(monkeypatch, capsys):
    """Retry while health is starting and succeed once healthy."""
    module = load_module(STACK, "wait-ready.py")
    states = iter([("true", "running", "starting"), ("true", "running", "healthy")])
    current = [None]
    sleeps = []

    def fake_run(command, **kwargs):
        """Return successive container states and health probe values."""
        if len(command) == 3:
            current[0] = next(states)
            return SimpleNamespace(returncode=0)
        template = command[3]
        value = {"{{.State.Running}}": current[0][0], "{{.State.Status}}": current[0][1],
                 "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}": current[0][2]}[template]
        return SimpleNamespace(returncode=0, stdout=value)

    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setenv("OPENWEBUI_READY_TIMEOUT", "10")
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.time, "sleep", sleeps.append)
    monkeypatch.setattr(module.time, "time", lambda: 100)
    module.main()
    assert sleeps == [2]
    assert "READY (running/healthy)" in capsys.readouterr().out


@pytest.mark.parametrize("timeout", ["-1", "not-a-number"])
def test_wait_ready_rejects_invalid_timeout(monkeypatch, timeout):
    """Reject negative and nonnumeric readiness timeouts."""
    module = load_module(STACK, "wait-ready.py")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setenv("OPENWEBUI_READY_TIMEOUT", timeout)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: pytest.fail("unexpected Docker call"))
    with pytest.raises(module.WaitError, match="invalido"):
        module.main()


@pytest.mark.parametrize("filename", ["reconcile-model-policy.py", "verify-model-policy.py"])
def test_policy_wrapper_requires_running_container(filename, monkeypatch, capsys):
    """Refuse policy operations when the container is stopped."""
    module = load_module(STACK, filename)
    commands = []

    def fake_run(command, **kwargs):
        """Report that the policy container is stopped."""
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="false\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module.main() == 1
    assert len(commands) == 1
    assert "not running" in capsys.readouterr().err


@pytest.mark.parametrize("filename", ["reconcile-model-policy.py", "verify-model-policy.py"])
def test_policy_wrapper_executes_expected_inner_script(filename, monkeypatch):
    """Execute the matching inner policy script and return its exit code."""
    module = load_module(STACK, filename)
    calls = []

    def fake_run(command, **kwargs):
        """Pass inspection and return the inner script's failure code."""
        calls.append((command, kwargs))
        if command[1] == "inspect":
            return SimpleNamespace(returncode=0, stdout="true\n")
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module.main() == 7
    assert calls[1][0] == ["docker", "exec", "-i", "open-webui", "python", "-"]
    script = calls[1][1]["input"]
    assert "basic_autorouter" in script
    assert "web_search" in script
    if filename.startswith("reconcile"):
        assert "grant_access" in script
        assert "await db.commit()" in script
    else:
        assert "get_grants_by_resource" in script
        assert "await db.commit()" not in script
