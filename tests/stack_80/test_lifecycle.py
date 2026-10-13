# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Protect deployment adoption, private stores, and explicit lifecycle boundaries."""

import sys
sys.dont_write_bytecode = True
import importlib
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.helpers import ROOT as PROJECT, load_module
from tests.test_stack_wrapper_cli import load_wrapper
from .verify import ROOT, SERVICES, CLIENT_ID


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """Use private fixture tokens and no real Docker or Google credentials."""
    stack = tmp_path / "stack-80_-_mcp"
    shutil.copytree(ROOT, stack, ignore=shutil.ignore_patterns(".env", ".lock", "__pycache__"))
    (tmp_path / ".env").write_text("fixture environment\n")
    (stack / ".env").symlink_to("../.env")
    api = importlib.import_module("stack-80_-_mcp.stack_env")
    monkeypatch.setattr(api, "ROOT", stack)
    config = {"networks": {"redlocal": {"name": "redlocal"}}, "services": {}}
    for name in SERVICES:
        data = tmp_path / "runtime" / f"service_-_{name}" / "data"
        for path in (data, data / "credentials", data / "attachments"):
            path.mkdir(parents=True, mode=0o700, exist_ok=True)
            path.chmod(0o700)
        (data / "credentials/token.json").write_text("fixture token to preserve")
        settings = stack / "config" / name / ".env"
        settings.write_text(settings.with_name(".env.example").read_text())
        settings.chmod(0o600)
        config["services"][name] = {
            "user": f"{os.getuid()}:{os.getgid()}", "volumes": [{"source": str(data)}],
            "environment": {"GOOGLE_OAUTH_CLIENT_ID": CLIENT_ID,
                            "GOOGLE_OAUTH_CLIENT_SECRET": "fixture-secret", "USER_GOOGLE_EMAIL": "agent@example.com"},
        }
    monkeypatch.setattr(api, "configuration", lambda: config)
    monkeypatch.setattr(api, "validate_network", lambda _: None)
    return stack, api, config


def configure_wrapper(deployment, monkeypatch):
    stack, api, _ = deployment
    wrapper = load_wrapper("80")
    monkeypatch.setattr(wrapper, "ROOT", stack.parent)
    monkeypatch.setattr(wrapper, "STACK_DIR", stack)
    monkeypatch.setattr(wrapper, "LOCK_FILE", stack / ".lock")
    monkeypatch.setattr(wrapper, "helper", lambda: api)
    monkeypatch.setattr(wrapper, "protected_text", lambda _: "fixture environment")
    monkeypatch.setattr(wrapper, "central_preflight", lambda: None)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    platform = stack.parent / "stack-00_-_platform"
    platform.mkdir()
    (platform / ".lock").write_text("prepared")
    return wrapper


def test_install_adopts_running_deployment_without_touching_tokens(deployment, monkeypatch):
    stack, api, config = deployment
    wrapper = configure_wrapper(deployment, monkeypatch)
    monkeypatch.setattr(wrapper, "container_rows", lambda _: {name: {"State": "running"} for name in SERVICES})
    before = {p: (p.read_bytes(), p.stat().st_mode, p.stat().st_uid) for p in stack.rglob(".env")}
    tokens = [Path(service["volumes"][0]["source"]) / "credentials/token.json" for service in config["services"].values()]
    calls = []
    def phase(label, command, **kwargs):
        calls.append(command)
        assert command[-1] == "--adopt"
        (stack / ".lock").write_text("adopted")
        return 0
    monkeypatch.setattr(wrapper, "run_phase", phase)
    assert wrapper.install() == 0
    assert len(calls) == 1
    assert all((p.read_bytes(), p.stat().st_mode, p.stat().st_uid) == metadata for p, metadata in before.items())
    assert all(p.read_text() == "fixture token to preserve" for p in tokens)
    assert wrapper.install() == 0
    assert len(calls) == 1


def test_running_adoption_refuses_settings_drift(deployment, monkeypatch):
    stack, _, _ = deployment
    settings = stack / "config/mcp-gmail/.env"
    settings.write_text("GOOGLE_OAUTH_CLIENT_SECRET=obsolete\nOTHER=keep\n")
    before = settings.read_bytes()
    wrapper = configure_wrapper(deployment, monkeypatch)
    monkeypatch.setattr(wrapper, "container_rows", lambda _: {"mcp-gmail": {"State": "running"}})
    monkeypatch.setattr(wrapper, "run_phase", lambda *args, **kwargs: pytest.fail("unexpected mutation"))
    assert wrapper.install() == 1
    assert not (stack / ".lock").exists()
    assert settings.read_bytes() == before


def test_fresh_install_sequences_platform_settings_prepare(deployment, monkeypatch):
    stack, api, _ = deployment
    wrapper = configure_wrapper(deployment, monkeypatch)
    monkeypatch.setattr(wrapper, "container_rows", lambda _: {})
    monkeypatch.setattr(api, "runtime_directories", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("not prepared")))
    calls = []
    def phase(label, command, **kwargs):
        calls.append(command)
        if command[-1].endswith("01-prepare.py"):
            (stack / ".lock").write_text("prepared")
        return 0
    monkeypatch.setattr(wrapper, "run_phase", phase)
    assert wrapper.install() == 0
    assert calls[0][-2:] == ["--stack", "80"]
    assert calls[1][-1].endswith("00-bootstrap.py")
    assert calls[2][-1].endswith("01-prepare.py")
    assert not any("up" in command or "authorize.py" in str(command) for command in calls)


def test_prepare_adopt_writes_lock_only(deployment, monkeypatch):
    stack, api, _ = deployment
    spec = importlib.util.spec_from_file_location("stack80_adopt_fixture", stack / "01-prepare.py")
    prepare = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "stack_env", api)
    spec.loader.exec_module(prepare)
    monkeypatch.setattr(sys, "argv", ["01-prepare.py", "--adopt"])
    before = {p: p.read_bytes() for p in stack.rglob("*") if p.is_file()}
    prepare.main()
    assert (stack / ".lock").is_file()
    assert all(p.read_bytes() == content for p, content in before.items())


def test_start_preflight_and_stop_preserve_data(deployment, monkeypatch):
    stack, _, _ = deployment
    wrapper = configure_wrapper(deployment, monkeypatch)
    calls = []
    monkeypatch.setattr(wrapper, "run_phase", lambda label, command: calls.append(command) or 0)
    assert wrapper.run_compose("up") == 1
    assert not calls
    (stack / ".lock").write_text("prepared")
    assert wrapper.run_compose("up") == 0
    assert calls[-1][-3:] == ["up", "-d", "--build"]
    (stack / ".lock").unlink()
    assert wrapper.run_compose("down") == 0
    assert calls[-1][-1] == "down"
    assert "--volumes" not in calls[-1]


def test_existing_runtime_metadata_and_symlinks_are_not_repaired(deployment):
    _, api, config = deployment
    path = Path(config["services"]["mcp-gmail"]["volumes"][0]["source"]) / "credentials"
    path.chmod(0o755)
    with pytest.raises(RuntimeError, match="0700"):
        api.runtime_directories(config, create=True)
    assert path.stat().st_mode & 0o777 == 0o755
    path.chmod(0o700)
    token = path / "token.json"
    token.unlink()
    path.rmdir()
    outside = path.parent / "outside"
    outside.mkdir()
    path.symlink_to(outside)
    with pytest.raises(RuntimeError, match="symlink"):
        api.runtime_directories(config, create=True)


def test_reconfig_preview_then_private_backup_is_idempotent(deployment, monkeypatch):
    stack, api, config = deployment
    module = load_module("stack-80_-_mcp", "reconfig.py")
    monkeypatch.setattr(module, "STACK_DIR", stack)
    monkeypatch.setattr(module, "environment", lambda _: {})
    monkeypatch.setattr(module, "container_rows", lambda _: {})
    path = stack / "config/mcp-gdrive/.env"
    path.write_text("OTHER=keep\nGOOGLE_OAUTH_CLIENT_SECRET=obsolete\n")
    before = path.read_bytes()
    assert module.main(False) == 0
    assert path.read_bytes() == before
    assert not list(path.parent.glob(".env-backup-*"))
    assert module.main(True) == 0
    assert path.read_text() == "OTHER=keep\n"
    backups = list(path.parent.glob(".env-backup-*"))
    assert len(backups) == 1 and backups[0].read_bytes() == before
    assert backups[0].stat().st_mode & 0o777 == 0o600
    assert module.main(True) == 0
    assert len(list(path.parent.glob(".env-backup-*"))) == 1
    for service in config["services"].values():
        assert (Path(service["volumes"][0]["source"]) / "credentials/token.json").read_text() == "fixture token to preserve"


def test_reconfig_refuses_changes_while_running(deployment, monkeypatch):
    stack, _, _ = deployment
    module = load_module("stack-80_-_mcp", "reconfig.py")
    monkeypatch.setattr(module, "STACK_DIR", stack)
    monkeypatch.setattr(module, "environment", lambda _: {})
    monkeypatch.setattr(module, "container_rows", lambda _: {"mcp-gmail": {"State": "running"}})
    path = stack / "config/mcp-gmail/.env"
    path.write_text("USER_GOOGLE_EMAIL=old@example.com\n")
    before = path.read_bytes()
    assert module.main(True) == 1
    assert path.read_bytes() == before
    assert not list(path.parent.glob(".env-backup-*"))


def test_platform_stack80_layout_preserves_existing_stores(deployment, monkeypatch):
    stack, _, _ = deployment
    platform = load_module("stack-00_-_platform", "00-bootstrap.py")
    specs = dict(platform.build_layout({"BASE_PATH": str(stack.parent / "runtime"),
                    "MCP_UID": str(os.getuid()), "MCP_GID": str(os.getgid())}))["stack-80_-_mcp"]()
    assert len(specs) == 12 and all(spec.create_only for spec in specs)
    monkeypatch.setattr(platform.os, "chown", lambda *a: pytest.fail("unexpected chown"))
    monkeypatch.setattr(platform.os, "chmod", lambda *a: pytest.fail("unexpected chmod"))
    for spec in specs:
        platform.ensure_dir(spec)


def test_deep_status_checks_tools_without_authorization(deployment, monkeypatch, capsys):
    stack, _, _ = deployment
    from wrapper.lib import stack_status
    (stack / ".lock").write_text("prepared")
    rows = {name: {"State": "running", "Health": "healthy"} for name in SERVICES}
    monkeypatch.setattr(stack_status, "container_rows", lambda _: rows)
    calls = []
    monkeypatch.setattr(stack_status, "mcp_probe", lambda name: calls.append(name) or name != "mcp-gmail")
    assert stack_status.report_status("80", stack, stack / ".lock", deep=True) == 1
    assert tuple(calls) == SERVICES
    assert "Google authorization/access: NOT CHECKED" in capsys.readouterr().out


def test_cli_discovers_stack80_and_completes_reconfig():
    result = subprocess.run([sys.executable, "-B", str(PROJECT / "local-ai"), "__complete", "stack-80", "reconfig", ""],
                            capture_output=True, text=True)
    assert result.returncode == 0 and "--apply" in result.stdout


def test_invalid_central_key_stops_before_any_mutation(deployment, monkeypatch, capsys):
    stack, _, _ = deployment
    wrapper = load_wrapper("80")
    monkeypatch.setattr(wrapper, "ROOT", stack.parent)
    monkeypatch.setattr(wrapper, "STACK_DIR", stack)
    monkeypatch.setattr(wrapper, "LOCK_FILE", stack / ".lock")
    platform = stack.parent / "stack-00_-_platform"
    platform.mkdir()
    (platform / ".lock").write_text("prepared")
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(wrapper, "protected_text", lambda _: "BASE_PATH=/runtime\nNETWORK_NAME=redlocal\nGOOGLE_WORKSPACE_MCP_VERSION=2.1.0\n")
    monkeypatch.setattr(wrapper, "container_rows", lambda _: pytest.fail("preflight should fail first"))
    assert wrapper.install() == 1
    assert "MCP_GOOGLE_OAUTH_CLIENT_ID" in capsys.readouterr().err
    assert not (stack / ".lock").exists()


def test_deep_probe_executes_only_initialization_and_listing(monkeypatch):
    from wrapper.lib import stack_status
    from types import ModuleType
    calls = []
    class Context:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
    class Session(Context):
        def __init__(self, *args):
            pass
        async def initialize(self):
            calls.append("initialize")
        async def list_tools(self):
            calls.append("list_tools")
            return SimpleNamespace(tools=["fixture"])
    class Transport(Context):
        async def __aenter__(self):
            return object(), object()
    httpx = ModuleType("httpx2")
    httpx.AsyncClient = lambda **kwargs: Context()
    mcp = ModuleType("mcp")
    mcp.ClientSession = Session
    transport = ModuleType("mcp.client.streamable_http")
    transport.streamable_http_client = lambda *args, **kwargs: Transport()
    for name, module in (("httpx2", httpx), ("mcp", mcp), ("mcp.client.streamable_http", transport)):
        monkeypatch.setitem(sys.modules, name, module)
    def run(command, **kwargs):
        assert command[:3] == ["docker", "exec", "mcp-gmail"]
        assert kwargs["timeout"] == 30
        exec(compile(command[-1], "<mcp-status-probe>", "exec"), {})
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(stack_status.subprocess, "run", run)
    assert stack_status.mcp_probe("mcp-gmail")
    assert calls == ["initialize", "list_tools"]


def test_prepare_failure_does_not_record_installation(deployment, monkeypatch):
    stack, api, _ = deployment
    wrapper = configure_wrapper(deployment, monkeypatch)
    monkeypatch.setattr(wrapper, "container_rows", lambda _: {})
    monkeypatch.setattr(api, "runtime_directories", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("missing store")))
    calls = []
    def phase(label, command, **kwargs):
        calls.append(command)
        return 7 if command[-1].endswith("01-prepare.py") else 0
    monkeypatch.setattr(wrapper, "run_phase", phase)
    assert wrapper.install() == 7
    assert not (stack / ".lock").exists()
    assert len(calls) == 3


def test_unsafe_lock_and_settings_links_are_rejected(deployment, monkeypatch):
    stack, api, _ = deployment
    wrapper = configure_wrapper(deployment, monkeypatch)
    target = stack / "outside"
    target.write_text("preserve")
    (stack / ".lock").symlink_to(target)
    monkeypatch.setattr(wrapper, "container_rows", lambda _: pytest.fail("unsafe lock must fail first"))
    assert wrapper.install() == 1
    settings = stack / "config/mcp-gmail/.env"
    settings.unlink()
    settings.symlink_to(target)
    with pytest.raises(RuntimeError, match="symlink"):
        api.settings_changes(SERVICES)
    assert target.read_text() == "preserve"
