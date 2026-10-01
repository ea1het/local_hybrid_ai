# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Exercise Stack 00 platform scripts without modifying the host.

Tests use temporary directories and mocked subprocess or OS calls to check
bootstrap, certificate handling, environment links, and readiness
verification. They focus on lock behavior and refusal of unsafe paths.
Importing this module does not execute the operational scripts."""

import sys

sys.dont_write_bytecode = True

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.helpers import load_module


STACK = "stack-00_-_platform"


def module(filename: str):
    """Load a Stack 00 module for isolated behavior checks."""
    return load_module(STACK, filename)


def test_bootstrap_validates_numbers_and_refuses_symlink(tmp_path):
    """Validate numeric settings and reject symlinked directories."""
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


def test_bootstrap_keeps_correct_directory_metadata(tmp_path, monkeypatch):
    """Avoid repeating ownership and mode changes on an already-correct path."""
    bootstrap = module("00-bootstrap.py")
    directory = tmp_path / "service"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    stat_result = directory.stat()
    monkeypatch.setattr(bootstrap.os, "chown", lambda *args: pytest.fail("unexpected chown"))
    monkeypatch.setattr(bootstrap.os, "chmod", lambda *args: pytest.fail("unexpected chmod"))

    bootstrap.ensure_dir(bootstrap.Dir(directory, 0o700, stat_result.st_uid, stat_result.st_gid))


def test_bootstrap_rechecks_platform_despite_own_lock(tmp_path, monkeypatch):
    """Audit Stack0 directories but preserve other locked stacks."""
    bootstrap = module("00-bootstrap.py")
    platform = tmp_path / STACK
    other = tmp_path / "stack-10_-_haproxy_web"
    for directory in (platform, other):
        directory.mkdir()
        (directory / ".lock").touch()
    monkeypatch.setattr(bootstrap, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(bootstrap, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(bootstrap.os, "geteuid", lambda: 0)
    monkeypatch.setattr(bootstrap.shutil, "which", lambda command: "/fake/groupadd")
    monkeypatch.setattr(bootstrap, "load_env", lambda path: {
        "STACKS_ROOT": str(tmp_path), "BASE_PATH": str(tmp_path / "runtime"), "PLATFORM_PKI_GID": "1999"
    })
    monkeypatch.setattr(bootstrap, "ensure_group", lambda *args: None)
    monkeypatch.setattr(bootstrap, "parse_args", lambda: SimpleNamespace(dry_run=False, platform_only=False))
    monkeypatch.setattr(bootstrap, "build_layout", lambda env: [
        (STACK, lambda: [bootstrap.Dir(tmp_path / "platform-state", 0o700)]),
        (other.name, lambda: pytest.fail("locked stack must not be rebuilt")),
    ])
    visited = []
    monkeypatch.setattr(bootstrap, "ensure_dir", visited.append)

    bootstrap.main()
    assert [spec.path.name for spec in visited] == ["platform-state"]


def test_bootstrap_platform_scope_skips_unlocked_application_stacks(tmp_path, monkeypatch):
    """Limit installer reconciliation to platform and HAProxy prerequisites."""
    bootstrap = module("00-bootstrap.py")
    monkeypatch.setattr(bootstrap, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(bootstrap, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(bootstrap.os, "geteuid", lambda: 0)
    monkeypatch.setattr(bootstrap.shutil, "which", lambda command: "/fake/groupadd")
    monkeypatch.setattr(bootstrap, "load_env", lambda path: {
        "STACKS_ROOT": str(tmp_path), "BASE_PATH": str(tmp_path / "runtime"), "PLATFORM_PKI_GID": "1999"
    })
    monkeypatch.setattr(bootstrap, "ensure_group", lambda *args: None)
    monkeypatch.setattr(bootstrap, "parse_args", lambda: SimpleNamespace(dry_run=False, platform_only=True))
    monkeypatch.setattr(bootstrap, "build_layout", lambda env: [
        (STACK, lambda: [bootstrap.Dir(tmp_path / "platform", 0o750)]),
        ("stack-10_-_haproxy_web", lambda: [bootstrap.Dir(tmp_path / "haproxy", 0o750)]),
        ("stack-40_-_gitea", lambda: pytest.fail("unlocked application stack must not be touched")),
    ])
    visited = []
    monkeypatch.setattr(bootstrap, "ensure_dir", visited.append)

    bootstrap.main()
    assert [spec.path.name for spec in visited] == ["platform", "haproxy"]


def test_prepare_with_lock_still_checks_prerequisites(tmp_path, monkeypatch):
    """Do not let an existing lock hide a missing operational environment."""
    prepare = module("01-prepare.py")
    stack = tmp_path / STACK
    stack.mkdir()
    (stack / ".lock").write_text("prepared")
    monkeypatch.setattr(prepare, "__file__", str(stack / "01-prepare.py"))
    monkeypatch.setattr(prepare, "require_root", lambda: None)
    monkeypatch.setattr(prepare, "require_commands", lambda *args: None)
    monkeypatch.setattr(prepare, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    with pytest.raises(SystemExit):
        prepare.main()


def test_ca_installer_validates_name_and_rejects_symlink(tmp_path, monkeypatch):
    """Validate CA names and refuse symlinked certificate sources."""
    ca = module("install-ca-cert.py")
    monkeypatch.setattr(ca, "SYSTEM_CA_DIR", tmp_path)
    assert ca.local_ca_path({"LOCAL_CA_NAME": "local-ai"}) == tmp_path / "local-ai.crt"
    with pytest.raises(SystemExit):
        ca.local_ca_path({"LOCAL_CA_NAME": "../unsafe"})
    assert ca.source_path({"LOCAL_CA_SOURCE_PATH": str(tmp_path / "rootCA.pem")}) == tmp_path / "rootCA.pem"
    with pytest.raises(SystemExit):
        ca.source_path({"LOCAL_CA_SOURCE_PATH": "relative/rootCA.pem"})
    source = tmp_path / "source.pem"
    source.write_text("certificate")
    link = tmp_path / "link.pem"
    link.symlink_to(source)
    with pytest.raises(SystemExit):
        ca.find_ca(link)


def test_ca_installer_keeps_trusted_destination_without_source(tmp_path, monkeypatch):
    """A healthy CA needs no copied PEM, even with a preparation lock."""
    ca = module("install-ca-cert.py")
    destination = tmp_path / "local.crt"
    destination.write_text("existing CA")
    monkeypatch.setattr(ca, "parse_args", lambda: SimpleNamespace(ca=tmp_path / "missing.pem", force=False))
    monkeypatch.setattr(ca, "require_root", lambda: None)
    monkeypatch.setattr(ca, "require_commands", lambda: None)
    monkeypatch.setattr(ca, "load_env", lambda path: {"LOCAL_CA_NAME": "local"})
    monkeypatch.setattr(ca, "SYSTEM_CA_DIR", tmp_path)
    monkeypatch.setattr(ca, "certificate_valid", lambda path: True)
    monkeypatch.setattr(ca, "bundle_trusts", lambda path: True)
    monkeypatch.setattr(ca, "verify_bundle", lambda path: None)
    monkeypatch.setattr(ca, "find_ca", lambda path: pytest.fail("source must not be required"))
    monkeypatch.setattr(ca.os, "chown", lambda *args: None)

    ca.main()


def test_ca_installer_repairs_missing_destination(tmp_path, monkeypatch):
    """Install and verify a missing CA from the supplied source."""
    ca = module("install-ca-cert.py")
    destination = tmp_path / "local.crt"
    source = tmp_path / "rootCA.pem"
    source.write_text("source CA")
    monkeypatch.setattr(ca, "parse_args", lambda: SimpleNamespace(ca=None, force=False))
    monkeypatch.setattr(ca, "require_root", lambda: None)
    monkeypatch.setattr(ca, "require_commands", lambda: None)
    monkeypatch.setattr(ca, "load_env", lambda path: {
        "LOCAL_CA_NAME": "local", "LOCAL_CA_SOURCE_PATH": str(source)
    })
    monkeypatch.setattr(ca, "SYSTEM_CA_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(ca, "validate_ca", lambda path: calls.append("validate"))
    monkeypatch.setattr(ca, "install_ca_on_host", lambda path, dest: calls.append("install"))
    monkeypatch.setattr(ca, "verify_bundle", lambda path: calls.append("verify"))

    ca.main()
    assert calls == ["validate", "install", "verify"]


def test_tls_installer_checks_domains_and_atomic_copy(tmp_path, monkeypatch):
    """Validate SAN names and avoid replacing unchanged TLS files."""
    tls = module("install-tls-certs.py")
    assert tls.parse_san_domains("one.local, two.local") == ["one.local", "two.local"]
    with pytest.raises(SystemExit):
        tls.parse_san_domains("../unsafe")
    assert tls.source_path({"TLS_CERT_SOURCE_PATH": str(tmp_path / "tls.crt")},
                           "TLS_CERT_SOURCE_PATH") == tmp_path / "tls.crt"
    with pytest.raises(SystemExit):
        tls.source_path({"TLS_KEY_SOURCE_PATH": "relative/tls.key"}, "TLS_KEY_SOURCE_PATH")
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_bytes(b"certificate")
    monkeypatch.setattr(tls.os, "chown", lambda *_: None)
    monkeypatch.setattr(tls, "ensure_metadata", lambda *args: False)
    assert tls.install_atomic(source, target, 0o640, 42)
    assert target.read_bytes() == b"certificate"
    assert not tls.install_atomic(source, target, 0o640, 42)
    target.unlink()
    target.symlink_to(source)
    with pytest.raises(SystemExit):
        tls.install_atomic(source, target, 0o640, 42)


def test_tls_installer_keeps_healthy_pair_without_sources(tmp_path, monkeypatch):
    """Preserve an installed valid pair while repairing only metadata."""
    tls = module("install-tls-certs.py")
    target_dir = tmp_path / "service_-_haproxy" / "config"
    target_dir.mkdir(parents=True)
    ca = tmp_path / "ca.crt"
    ca.write_text("CA")
    missing = tmp_path / "missing"
    monkeypatch.setattr(tls, "parse_args", lambda: SimpleNamespace(cert=missing, key=missing, ca=ca, renew=False))
    monkeypatch.setattr(tls.os, "geteuid", lambda: 0)
    monkeypatch.setattr(tls.shutil, "which", lambda name: "/fake/openssl")
    monkeypatch.setattr(tls, "load_env", lambda path: {
        "BASE_PATH": str(tmp_path), "TLS_SAN_DOMAINS": "one.local", "PLATFORM_PKI_GID": "1999"
    })
    monkeypatch.setattr(tls, "pair_healthy", lambda *args: True)
    monkeypatch.setattr(tls, "ensure_metadata", lambda *args: False)
    monkeypatch.setattr(tls, "validate_pair", lambda *args: pytest.fail("source must not be required"))

    tls.main()


def test_tls_installer_repairs_missing_pair(tmp_path, monkeypatch):
    """Use validated source material when installed TLS files are missing."""
    tls = module("install-tls-certs.py")
    target_dir = tmp_path / "service_-_haproxy" / "config"
    target_dir.mkdir(parents=True)
    ca = tmp_path / "ca.crt"
    cert = tmp_path / "source.crt"
    key = tmp_path / "source.key"
    for path in (ca, cert, key):
        path.write_text("source")
    monkeypatch.setattr(tls, "parse_args", lambda: SimpleNamespace(cert=None, key=None, ca=ca, renew=False))
    monkeypatch.setattr(tls.os, "geteuid", lambda: 0)
    monkeypatch.setattr(tls.shutil, "which", lambda name: "/fake/openssl")
    monkeypatch.setattr(tls, "load_env", lambda path: {
        "BASE_PATH": str(tmp_path), "TLS_SAN_DOMAINS": "one.local", "PLATFORM_PKI_GID": "1999",
        "TLS_CERT_SOURCE_PATH": str(cert), "TLS_KEY_SOURCE_PATH": str(key)
    })
    calls = []
    monkeypatch.setattr(tls, "validate_pair", lambda *args: calls.append("validate"))
    monkeypatch.setattr(tls, "install_atomic", lambda *args: calls.append("install") or True)
    monkeypatch.setattr(tls, "haproxy_running", lambda: False)

    tls.main()
    assert calls == ["validate", "install", "install"]


def test_installer_creates_lock_only_after_success(tmp_path, monkeypatch):
    """Write the installation lock only after every step succeeds."""
    installer = module("install.py")
    stack = tmp_path / STACK
    stack.mkdir()
    monkeypatch.setattr(installer, "__file__", str(stack / "install.py"))
    calls = []

    def run(command, **_kwargs):
        """Record installer steps and fail the simulated verification step."""
        calls.append((Path(command[2]).name, command[3:]))
        return SimpleNamespace(returncode=2 if command[2].endswith("verify.py") else 0)

    monkeypatch.setattr(installer.subprocess, "run", run)
    with pytest.raises(SystemExit) as failure:
        installer.main()
    assert failure.value.code == 2
    assert not (stack / ".lock").exists()
    expected = [("00-bootstrap.py", ["--platform-only"]), ("01-prepare.py", []),
                ("install-ca-cert.py", []), ("install-tls-certs.py", []), ("verify.py", [])]
    assert calls == expected

    calls.clear()
    monkeypatch.setattr(installer.subprocess, "run", lambda command, **_kwargs: (
        calls.append((Path(command[2]).name, command[3:])) or SimpleNamespace(returncode=0)
    ))
    installer.main()
    assert (stack / ".lock").exists()
    calls.clear()
    installer.main()
    assert calls == expected

    calls.clear()
    monkeypatch.setattr(installer.subprocess, "run", run)
    with pytest.raises(SystemExit) as failure:
        installer.main()
    assert failure.value.code == 2
    assert not (stack / ".lock").exists()


def test_common_env_loading_and_required_values(tmp_path):
    """Parse quoted environment values and reject missing required keys."""
    common = module("ops_common.py")
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_STACK_VALUE='two words'\n")
    assert common.load_env(env_file)["TEST_STACK_VALUE"] == "two words"
    with pytest.raises(SystemExit):
        common.require({}, env_file, "MISSING")


def test_verifier_rejects_symlinks_and_missing_env(tmp_path, monkeypatch):
    """Reject symlinked inputs and incomplete verification environments."""
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
