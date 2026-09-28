# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import sys

sys.dont_write_bytecode = True

from types import SimpleNamespace

import pytest

from tests.helpers import load_module


prepare = load_module("stack-60_-_hermes", "01-prepare.py")
buzz = load_module("stack-60_-_hermes", "install-buzz.py")
sidecars = load_module("stack-60_-_hermes", "prepare-maintenance-sidecars.py")
git_memory = load_module("stack-60_-_hermes", "prepare-git-memory.py")


def test_prepare_model_default_only_uses_model_section():
    text = "other:\n  default: wrong\nmodel:\n  default: ${HERMES_MODEL}\nother:\n  default: later\n"
    assert prepare.model_default(text) == "${HERMES_MODEL}"
    assert prepare.model_default("model:\n  sibling: value\nnext:\n  default: wrong\n") == ""


def test_prepare_rejects_missing_dependency_before_writing(tmp_path, monkeypatch, capsys):
    stack = tmp_path / "stack-60_-_hermes"
    stack.mkdir()
    (tmp_path / "stack-00_-_platform").mkdir()
    (tmp_path / "stack-00_-_platform" / ".lock").touch()
    env = {key: "value" for key in prepare.ALL_KEYS}
    env.update(STACKS_ROOT=str(tmp_path), BASE_PATH=str(tmp_path / "runtime"),
               API_SERVER_KEY="abcdefgh", LITELLM_MCP_API_KEY="abcdefgh",
               LITELLM_MCP_URL="http://litellm/mcp", HERMES_VERSION="v1",
               TELEGRAM_BOT_TOKEN="",
               HERMES_SERVICE="service_-_hermes", HERMES_MEMORY_SERVICE="service_-_memory",
               MEMORY_SYNC_SERVICE="service_-_sync", SANDBOX_SERVICE="service_-_sandbox")
    env_file = stack / ".env"
    env_file.write_text("".join(f"{key}={value}\n" for key, value in env.items()))
    monkeypatch.setattr(prepare, "STACK_DIR", stack)
    monkeypatch.setattr(prepare, "ENV_FILE", env_file)

    with pytest.raises(SystemExit, match="1"):
        prepare.Prepare()
    assert "Stack3" in capsys.readouterr().err
    assert sorted(path.name for path in stack.iterdir()) == [".env"]


def test_buzz_rejects_unsafe_base_before_install(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    dockerfile = tmp_path / "Dockerfile"
    env_file.touch()
    dockerfile.touch()
    monkeypatch.setattr(buzz, "ENV_FILE", env_file)
    monkeypatch.setattr(buzz, "DOCKERFILE", dockerfile)
    monkeypatch.setattr(buzz.os, "geteuid", lambda: 0)
    monkeypatch.setattr(buzz.shutil, "which", lambda command: "/fake/" + command)
    monkeypatch.setattr(buzz, "load_env", lambda path: {
        "BASE_PATH": "/", "HERMES_SERVICE": "service_-_hermes", "HERMES_UID": "1000",
        "HERMES_GID": "1000", "HERMES_IMAGE": "hermes", "HERMES_VERSION": "v1",
    })
    calls = []
    monkeypatch.setattr(buzz, "run", lambda *args, **kwargs: calls.append(args) or SimpleNamespace(returncode=0))

    with pytest.raises(SystemExit, match="1"):
        buzz.main()
    assert "absolute non-root" in capsys.readouterr().err
    assert calls == [("docker", "version")]


def test_buzz_regular_rejects_symlink(tmp_path):
    binary = tmp_path / "buzz"
    binary.write_text("binary")
    link = tmp_path / "linked"
    link.symlink_to(binary)
    assert buzz.regular(binary)
    assert not buzz.regular(link)


def test_sidecars_require_dedicated_ssh_material(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    lock_file = tmp_path / ".lock"
    env_file.touch()
    lock_file.touch()
    monkeypatch.setattr(sidecars, "ENV_FILE", env_file)
    monkeypatch.setattr(sidecars, "LOCK_FILE", lock_file)
    monkeypatch.setattr(sidecars.os, "geteuid", lambda: 0)
    monkeypatch.setattr(sidecars, "load_env", lambda path: {
        "BASE_PATH": str(tmp_path), "HERMES_UID": "1000", "HERMES_GID": "1000",
        "MEMORY_SYNC_SERVICE": "service_-_sync", "SANDBOX_SERVICE": "service_-_sandbox",
    })
    commands = []

    def fake_install(command, **kwargs):
        commands.append(command)
        if command[0] == "install":
            path = tmp_path / command[-1]
            path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(sidecars.subprocess, "run", fake_install)

    with pytest.raises(SystemExit, match="1"):
        sidecars.main()
    assert len(commands) == 3
    assert "ssh_config" in capsys.readouterr().err


@pytest.mark.parametrize("relative", ["../escape", ".git/config", "/outside"])
def test_git_memory_rejects_unsafe_tracked_paths(tmp_path, relative):
    with pytest.raises(SystemExit, match="1"):
        git_memory.validate_static_path(tmp_path, relative)


def test_git_memory_rejects_symlinked_static_file(tmp_path):
    (tmp_path / "real").write_text("data")
    (tmp_path / "linked").symlink_to(tmp_path / "real")
    with pytest.raises(SystemExit, match="1"):
        git_memory.validate_static_path(tmp_path, "linked")


def test_git_memory_adoption_rejects_unmanaged_local_file_before_clone(tmp_path, monkeypatch):
    memory_root = tmp_path / "memory"
    data = memory_root / "data"
    data.mkdir(parents=True)
    (data / "unmanaged.txt").write_text("keep")
    monkeypatch.setattr(git_memory, "run", lambda *args, **kwargs: pytest.fail("must not clone"))

    with pytest.raises(SystemExit, match="1"):
        git_memory.adopt(memory_root, data, tmp_path / "legacy", "remote", "main", 1000, 1000)
    assert (data / "unmanaged.txt").read_text() == "keep"
