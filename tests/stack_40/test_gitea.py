import sys

sys.dont_write_bytecode = True

import os
import subprocess
from types import SimpleNamespace

import pytest

from tests.helpers import load_module


STACK = "stack-40_-_gitea"


def test_prepare_renders_configuration_and_preserves_runner_token(tmp_path, monkeypatch):
    module = load_module(STACK, "01-prepare.py")
    stack_dir = tmp_path / STACK
    stack_dir.mkdir()
    base = tmp_path / "runtime"
    (tmp_path / "stack-00_-_platform").mkdir()
    (tmp_path / "stack-00_-_platform/.lock").touch()
    for name in ("service_-_gitea/config/conf", "service_-_gitea/data",
                 "service_-_gitea-runner/data", "service_-_gitea-runner/secret"):
        (base / name).mkdir(parents=True)
    (stack_dir / "config/gitea").mkdir(parents=True)
    (stack_dir / "config/gitea-runner").mkdir(parents=True)
    (stack_dir / "config/gitea/app.ini").write_text("domain=@@GITEA_DOMAIN@@\n")
    (stack_dir / "config/gitea-runner/config.yaml").write_text("network: @@GITEA_DOCKER_NETWORK@@\n")
    token = base / "service_-_gitea-runner/secret/registration-token"
    token.write_text("persistent-token\n")
    env = {
        "STACKS_ROOT": str(tmp_path), "BASE_PATH": str(base), "NETWORK_NAME": "internal",
        "GITEA_IMAGE": "gitea", "GITEA_CONTAINER_NAME": "gitea", "GITEA_UID": "1000",
        "GITEA_GID": "1000", "GITEA_SSH_BIND": "127.0.0.1", "GITEA_SSH_PORT": "2222",
        "GITEA_DOCKER_NETWORK": "internal", "GITEA_DOMAIN": "git.example.test",
        "GITEA_ROOT_URL": "https://git.example.test/", "GITEA_SSH_DOMAIN": "git.example.test",
        "GITEA_TIMEZONE": "UTC", "GITEA_INTERNAL_TOKEN": "internal-token",
        "GITEA_JWT_SECRET": "jwt-secret", "GITEA_ADMIN_USERNAME": "admin",
        "GITEA_ADMIN_EMAIL": "admin@example.test", "GITEA_ADMIN_PASSWORD": "password",
        "GITEA_RUNNER_NAME": "runner", "GITEA_RUNNER_INSTANCE_URL": "http://gitea:3000/",
    }
    (stack_dir / ".env").touch()
    (stack_dir / "docker-compose.yml").touch()
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[0] == "bash":
            return SimpleNamespace(returncode=0, stdout=b"\0".join(
                f"{key}={value}".encode() for key, value in env.items()) + b"\0")
        return SimpleNamespace(returncode=0, stdout="bridge\n")

    monkeypatch.setattr(module, "STACK_DIR", stack_dir)
    monkeypatch.setattr(module, "ENV_FILE", stack_dir / ".env")
    monkeypatch.setattr(module, "COMPOSE_FILE", stack_dir / "docker-compose.yml")
    monkeypatch.setattr(module, "LOCK_FILE", stack_dir / ".lock")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.os, "chown", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.os, "environ", os.environ.copy())
    monkeypatch.setattr(module.shutil, "which", lambda command: "/fake/" + command)
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    module.main()

    assert token.read_text() == "persistent-token\n"
    assert (base / "service_-_gitea/config/app.ini").read_text() == "domain=git.example.test\n"
    assert (base / "service_-_gitea/config/conf/app.ini").read_text() == "domain=git.example.test\n"
    assert (base / "service_-_gitea-runner/data/config.yaml").read_text() == "network: internal\n"
    assert (base / "service_-_gitea/config/conf/app.ini").readlink().as_posix() == "../app.ini"
    assert "stack=stack-40_-_gitea" in (stack_dir / ".lock").read_text()
    assert any(command[-2:] == ["config", "--quiet"] for command in commands)
    assert not any(command[:3] == ["openssl", "rand", "-hex"] for command in commands)


def test_prepare_rejects_unresolved_template_without_target_write(tmp_path):
    module = load_module(STACK, "01-prepare.py")
    source = tmp_path / "app.ini"
    target = tmp_path / "rendered.ini"
    source.write_text("domain=@@GITEA_DOMAIN@@ secret=@@MISSING@@")
    with pytest.raises(RuntimeError, match="placeholders sin resolver"):
        module.render(source, target, {"GITEA_DOMAIN": "git.example.test"})
    assert not target.exists()


def test_deploy_creates_missing_admin_and_waits_for_runner(tmp_path, monkeypatch):
    module = load_module(STACK, "deploy-gitea.py")
    stack_dir = tmp_path / STACK
    stack_dir.mkdir()
    base = tmp_path / "runtime"
    for name in ("service_-_gitea/config", "service_-_gitea-runner/data",
                 "service_-_gitea-runner/secret"):
        (base / name).mkdir(parents=True)
    (base / "service_-_gitea/config/app.ini").touch()
    (base / "service_-_gitea-runner/data/config.yaml").touch()
    (base / "service_-_gitea-runner/secret/registration-token").write_text("token")
    (stack_dir / ".env").touch()
    (stack_dir / ".lock").touch()
    env = {"STACKS_ROOT": str(tmp_path), "BASE_PATH": str(base), "GITEA_DOMAIN": "git.example.test",
           "GITEA_ROOT_URL": "https://git.example.test/", "GITEA_SSH_DOMAIN": "git.example.test",
           "GITEA_SSH_PORT": "2222", "GITEA_ADMIN_USERNAME": "admin",
           "GITEA_ADMIN_EMAIL": "admin@example.test", "GITEA_ADMIN_PASSWORD": "password",
           "GITEA_RUNNER_INSTANCE_URL": "http://gitea:3000/", "GITEA_RUNNER_NAME": "runner"}
    commands = []
    inspections = iter(["false", "true"])

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[0] == "bash":
            return SimpleNamespace(returncode=0, stdout=b"\0".join(
                f"{key}={value}".encode() for key, value in env.items()) + b"\0")
        if command[:2] == ["docker", "inspect"]:
            (base / "service_-_gitea-runner/data/.runner").write_text("identity")
            return SimpleNamespace(returncode=0, stdout=next(inspections))
        if "--admin" in command:
            return SimpleNamespace(returncode=0, stdout="other-user\n")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(module, "STACK_DIR", stack_dir)
    monkeypatch.setattr(module, "ENV_FILE", stack_dir / ".env")
    monkeypatch.setattr(module, "LOCK_FILE", stack_dir / ".lock")
    monkeypatch.setattr(module, "COMPOSE_FILE", stack_dir / "docker-compose.yml")
    monkeypatch.setattr(module.shutil, "which", lambda _: "/fake/docker")
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setattr(module.os, "environ", os.environ.copy())

    module.main()

    assert any("user create" in " ".join(command) for command in commands)
    assert any(command[-2:] == ["up", "-d"] for command in commands)
    assert len([command for command in commands if command[:2] == ["docker", "inspect"]]) == 2


def test_deploy_rejects_missing_runtime_token(tmp_path, monkeypatch):
    module = load_module(STACK, "deploy-gitea.py")
    stack_dir = tmp_path / STACK
    stack_dir.mkdir()
    (stack_dir / ".env").touch()
    (stack_dir / ".lock").touch()
    env = {key: "value" for key in ("GITEA_DOMAIN", "GITEA_ROOT_URL", "GITEA_SSH_DOMAIN",
           "GITEA_SSH_PORT", "GITEA_ADMIN_USERNAME", "GITEA_ADMIN_EMAIL",
           "GITEA_ADMIN_PASSWORD", "GITEA_RUNNER_INSTANCE_URL", "GITEA_RUNNER_NAME")}
    env.update(STACKS_ROOT=str(tmp_path), BASE_PATH=str(tmp_path / "runtime"))
    base = tmp_path / "runtime"
    (base / "service_-_gitea/config").mkdir(parents=True)
    (base / "service_-_gitea/config/app.ini").touch()
    (base / "service_-_gitea-runner/data").mkdir(parents=True)
    (base / "service_-_gitea-runner/data/config.yaml").touch()
    monkeypatch.setattr(module, "STACK_DIR", stack_dir)
    monkeypatch.setattr(module, "ENV_FILE", stack_dir / ".env")
    monkeypatch.setattr(module, "LOCK_FILE", stack_dir / ".lock")
    monkeypatch.setattr(module.shutil, "which", lambda _: "/fake/docker")
    monkeypatch.setattr(module.os, "environ", os.environ.copy())
    def fake_run(command, **kwargs):
        if command[0] == "bash":
            return SimpleNamespace(stdout=b"\0".join(f"{key}={value}".encode() for key, value in env.items()) + b"\0")
        if command[:3] == ["docker", "compose", "version"]:
            return SimpleNamespace(returncode=0)
        pytest.fail(f"unexpected command: {command}")
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="token runtime"):
        module.main()
