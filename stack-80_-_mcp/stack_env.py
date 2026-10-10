# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Shared selection and Compose access, without touching other stacks."""

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parent
SERVICES = ("mcp-gdrive", "mcp-gmail", "mcp-gcalendar")


def prepare_settings(services):
    """Prepare the shared link and preserve per-service signing identities."""
    path = ROOT / ".env"
    if path.exists() and not path.is_symlink():
        raise RuntimeError("Existing stack-local .env: preserve its values in the central .env "
                           "before removing it. Preparation will not overwrite it.")
    if not (ROOT.parent / ".env").is_file():
        raise RuntimeError("Missing central .env; prepare the global environment first.")
    if not path.is_symlink():
        path.symlink_to("../.env")
    central_environment()
    key = "FASTMCP_SERVER_AUTH_GOOGLE_JWT_SIGNING_KEY"
    for service in services:
        path = ROOT / "config" / service / ".env"
        if not path.exists():
            content = path.with_name(".env.example").read_text()
            with path.open("x") as output:
                os.chmod(path, 0o600)
                output.write(content)
        lines = path.read_text().splitlines()
        # The global Client ID is authoritative; discard obsolete local copies.
        lines = [line for line in lines if not line.startswith("GOOGLE_OAUTH_CLIENT_ID=")]
        existing = [line for line in lines if line.startswith(key + "=")]
        if not existing or not existing[0].split("=", 1)[1].strip():
            lines = [line for line in lines if not line.startswith(key + "=")]
            lines.append(f"{key}={secrets.token_hex(32)}")
        content = "\n".join(lines) + "\n"
        if path.read_text() != content:
            path.write_text(content)
        os.chmod(path, 0o600)
        print(f"{service}: settings prepared; signing key preserved.")


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


def compose(*arguments):
    env_file = central_environment()
    result = subprocess.run(
        ["docker", "compose", "--project-directory", str(ROOT),
         "--env-file", str(env_file), "-f", str(ROOT / "docker-compose.yml"),
         *arguments], capture_output=True, text=True, check=False,
    )
    if result.returncode:
        # Do not print rendered configuration: it contains local signing keys.
        raise RuntimeError("Docker Compose failed; check daemon access, .env files, "
                           "BASE_PATH and the service configuration.")
    return result.stdout


def configuration():
    return json.loads(compose("config", "--format", "json"))
