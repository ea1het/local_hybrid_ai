# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Shared selection and Compose access, without touching other stacks.

Importing this module does not prepare directories, change containers, or
perform Google authorization. Operations run only through explicit entrypoints.
"""

import sys

sys.dont_write_bytecode = True

import argparse
import json
import os
from pathlib import Path
import subprocess
import stat
import tempfile
import time

ROOT = Path(__file__).resolve().parent
SERVICES = ("mcp-gdrive", "mcp-gmail", "mcp-gcalendar")


def safe_path(path):
    """Reject symlinks throughout a managed path, including dangling links."""
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise RuntimeError(f"Managed path cannot contain a symlink: {path}")


def settings_changes(services):
    """Return desired content for changed private settings without writing."""
    changes = []
    for service in services:
        path = ROOT / "config" / service / ".env"
        safe_path(path)
        if path.exists() and not path.is_file():
            raise RuntimeError(f"Not a regular settings file: {path}")
        source = path if path.exists() else path.with_name(".env.example")
        safe_path(source)
        lines = source.read_text().splitlines()
        lines = [line for line in lines if not line.startswith((
            "GOOGLE_OAUTH_CLIENT_ID=", "GOOGLE_OAUTH_CLIENT_SECRET=", "USER_GOOGLE_EMAIL=",
            "FASTMCP_SERVER_AUTH_GOOGLE_JWT_SIGNING_KEY=",
            "# Generated locally by 01-prepare.py. This is NOT the Google client secret.",
        ))]
        content = ("\n".join(lines) + "\n").encode()
        if (not path.exists() or path.read_bytes() != content
                or stat.S_IMODE(path.stat().st_mode) != 0o600):
            changes.append((path, content))
    return changes


def apply_settings(changes):
    """Privately back up and atomically write settings; retain their owner."""
    for path, content in changes:
        safe_path(path)
        metadata = path.stat() if path.exists() else None
        if metadata:
            backup = path.with_name(f".env-backup-{time.time_ns()}")
            descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(path.read_bytes())
                if os.geteuid() == 0:
                    os.fchown(output.fileno(), metadata.st_uid, metadata.st_gid)
        descriptor, temporary = tempfile.mkstemp(prefix=".env-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as output:
                os.fchmod(output.fileno(), 0o600)
                if metadata and os.geteuid() == 0:
                    os.fchown(output.fileno(), metadata.st_uid, metadata.st_gid)
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def prepare_settings(services):
    """Prepare the shared link and private per-service settings."""
    path = ROOT / ".env"
    if path.exists() and not path.is_symlink():
        raise RuntimeError("Existing stack-local .env: preserve its values in the central .env "
                           "before removing it. Preparation will not overwrite it.")
    if not (ROOT.parent / ".env").is_file():
        raise RuntimeError("Missing central .env; prepare the global environment first.")
    if not path.is_symlink():
        path.symlink_to("../.env")
    central_environment()
    apply_settings(settings_changes(services))
    for service in services:
        print(f"{service}: settings prepared; Google configuration comes from central .env.")


def central_environment():
    """Require the canonical link; never replace existing operator settings."""
    path = ROOT / ".env"
    if not path.is_symlink() or os.readlink(path) != "../.env":
        raise RuntimeError("Stack 80 .env must be a symlink to ../.env; run 01-prepare.py.")
    if not path.is_file():
        raise RuntimeError("Missing central .env; prepare the global environment first.")
    return path


def parser(description):
    result = argparse.ArgumentParser(description=description)
    result.add_argument("--mcp", choices=SERVICES, action="append",
                        help="Select a service; repeat to select several. Default: all.")
    return result


def selected(args):
    return tuple(dict.fromkeys(args.mcp or SERVICES))


def compose_command(*arguments):
    """Build the canonical command, also used by interactive authorization."""
    env_file = central_environment()
    return ["docker", "compose", "--project-directory", str(ROOT),
            "--env-file", str(env_file), "-f", str(ROOT / "docker-compose.yml"),
            *arguments]


def compose(*arguments):
    result = subprocess.run(
        compose_command(*arguments), capture_output=True, text=True, check=False,
    )
    if result.returncode:
        # Do not print rendered configuration: it contains the Google secret.
        raise RuntimeError("Docker Compose failed; check daemon access, .env files, "
                           "BASE_PATH and the service configuration.")
    return result.stdout


def configuration():
    return json.loads(compose("config", "--format", "json"))


def validate_configuration(config, services=SERVICES):
    """Validate central Google settings and canonical data locations privately."""
    for name in services:
        service = config["services"][name]
        env = service["environment"]
        if not env.get("GOOGLE_OAUTH_CLIENT_ID", "").endswith(".apps.googleusercontent.com"):
            raise RuntimeError("Set MCP_GOOGLE_OAUTH_CLIENT_ID once in the central .env.")
        secret = env.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
        if not secret or secret.startswith("PUT_YOUR_"):
            raise RuntimeError("Set MCP_GOOGLE_OAUTH_CLIENT_SECRET once in the central .env.")
        email = env.get("USER_GOOGLE_EMAIL", "")
        if "@" not in email or email != email.strip() or email.startswith("PUT_YOUR_"):
            raise RuntimeError("Set MCP_GOOGLE_EMAIL once in the central .env.")
        data = Path(service["volumes"][0]["source"])
        if not data.is_absolute() or data == Path("/"):
            raise RuntimeError("BASE_PATH must be an absolute service runtime path.")
        uid, gid = service["user"].split(":")
        if not uid.isdigit() or not gid.isdigit():
            raise RuntimeError("MCP_UID and MCP_GID must be nonnegative integers.")
        safe_path(data)


def validate_network(config):
    """Inspect the existing bridge without creating or modifying networks."""
    network = config["networks"]["redlocal"]["name"]
    result = subprocess.run(["docker", "network", "inspect", network],
                            capture_output=True, text=True, check=False)
    if result.returncode or json.loads(result.stdout)[0]["Driver"] != "bridge":
        raise RuntimeError("An existing bridge redlocal network and running Docker daemon are required.")


def runtime_directories(config, services=SERVICES, *, create=False):
    """Create missing stores when requested; validate, never alter, existing ones."""
    for name in services:
        service = config["services"][name]
        uid, gid = (int(value) for value in service["user"].split(":"))
        if create and os.getuid() != 0 and (uid, gid) != (os.getuid(), os.getgid()):
            raise RuntimeError("Run preparation as root or as the configured MCP_UID/MCP_GID.")
        data = Path(service["volumes"][0]["source"])
        for path in (data, data / "credentials", data / "attachments"):
            safe_path(path)
            if not path.exists() and create:
                path.mkdir(parents=True, mode=0o700)
                if os.getuid() == 0:
                    os.chown(path, uid, gid)
            if not path.is_dir():
                raise RuntimeError(f"Missing runtime directory: {path}; run stack-80 install.")
            metadata = path.stat()
            if (metadata.st_uid, metadata.st_gid) != (uid, gid):
                raise RuntimeError(f"{name}: directory ownership differs from MCP_UID/MCP_GID: {path}")
            if stat.S_IMODE(metadata.st_mode) != 0o700:
                raise RuntimeError(f"{name}: directory must have mode 0700: {path}; review permissions manually.")
