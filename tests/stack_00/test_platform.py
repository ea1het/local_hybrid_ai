# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Isolated behavior checks for every Stack0 Python module."""

import sys

sys.dont_write_bytecode = True

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.helpers import load_module


STACK = "stack-00_-_platform"


def module(filename: str):
    return load_module(STACK, filename)


def test_bootstrap_validates_numbers_and_refuses_symlink(tmp_path):
    bootstrap = module("00-bootstrap.py")
    assert bootstrap.require_int({"UID": "42"}, "UID") == 42
    with pytest.raises(SystemExit):
        bootstrap.require_int({"UID": "bad"}, "UID")
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(SystemExit):
        bootstrap.ensure_dir(bootstrap.Dir(link, 0o750, None, None))


def test_prepare_with_lock_does_not_call_external_commands(tmp_path, monkeypatch):
    prepare = module("01-prepare.py")
    stack = tmp_path / STACK
    stack.mkdir()
    (stack / ".lock").write_text("prepared")
    monkeypatch.setattr(prepare, "__file__", str(stack / "01-prepare.py"))
    monkeypatch.setattr(prepare, "require_root", lambda: pytest.fail("locked stack must not be changed"))
    prepare.main()


def test_ca_installer_validates_name_and_rejects_symlink(tmp_path, monkeypatch):
    ca = module("install-ca-cert.py")
    monkeypatch.setattr(ca, "SYSTEM_CA_DIR", tmp_path)
    assert ca.local_ca_path({"LOCAL_CA_NAME": "local-ai"}) == tmp_path / "local-ai.crt"
    with pytest.raises(SystemExit):
        ca.local_ca_path({"LOCAL_CA_NAME": "../unsafe"})
    source = tmp_path / "source.pem"
    source.write_text("certificate")
    link = tmp_path / "link.pem"
    link.symlink_to(source)
    with pytest.raises(SystemExit):
        ca.find_ca(link)


def test_tls_installer_checks_domains_and_atomic_copy(tmp_path, monkeypatch):
    tls = module("install-tls-certs.py")
    assert tls.parse_san_domains("one.local, two.local") == ["one.local", "two.local"]
    with pytest.raises(SystemExit):
        tls.parse_san_domains("../unsafe")
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_bytes(b"certificate")
    monkeypatch.setattr(tls.os, "chown", lambda *_: None)
    assert tls.install_atomic(source, target, 0o640, 42)
    assert target.read_bytes() == b"certificate"
    assert not tls.install_atomic(source, target, 0o640, 42)
    target.unlink()
    target.symlink_to(source)
    with pytest.raises(SystemExit):
        tls.install_atomic(source, target, 0o640, 42)


def test_installer_creates_lock_only_after_success(tmp_path, monkeypatch):
    installer = module("install.py")
    stack = tmp_path / STACK
    stack.mkdir()
    monkeypatch.setattr(installer, "__file__", str(stack / "install.py"))
    calls = []

    def run(command, **_kwargs):
        calls.append(Path(command[-1]).name)
        return SimpleNamespace(returncode=2 if command[-1].endswith("verify.py") else 0)

    monkeypatch.setattr(installer.subprocess, "run", run)
    with pytest.raises(SystemExit) as failure:
        installer.main()
    assert failure.value.code == 2
    assert not (stack / ".lock").exists()
    assert calls == ["00-bootstrap.py", "01-prepare.py", "install-ca-cert.py", "install-tls-certs.py", "verify.py"]

    calls.clear()
    monkeypatch.setattr(installer.subprocess, "run", lambda command, **_kwargs: (
        calls.append(Path(command[-1]).name) or SimpleNamespace(returncode=0)
    ))
    installer.main()
    assert (stack / ".lock").exists()
    calls.clear()
    installer.main()
    assert calls == ["verify.py"]


def test_common_env_loading_and_required_values(tmp_path):
    common = module("ops_common.py")
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_STACK_VALUE='two words'\n")
    assert common.load_env(env_file)["TEST_STACK_VALUE"] == "two words"
    with pytest.raises(SystemExit):
        common.require({}, env_file, "MISSING")


def test_verifier_rejects_symlinks_and_missing_env(tmp_path, monkeypatch):
    verify = module("verify.py")
    regular = tmp_path / "regular"
    regular.write_text("data")
    link = tmp_path / "link"
    link.symlink_to(regular)
    assert verify.real_nonempty_file(regular)
    assert not verify.real_nonempty_file(link)
    stack = tmp_path / STACK
    stack.mkdir()
    monkeypatch.setattr(verify, "__file__", str(stack / "verify.py"))
    monkeypatch.setattr(verify, "require_root", lambda: None)
    monkeypatch.setattr(verify, "require_commands", lambda *_: None)
    with pytest.raises(SystemExit):
        verify.main()
