# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Validate settings, the existing network, and per-MCP data directories."""

import json
import os
from pathlib import Path
import subprocess

from stack_env import configuration, parser, prepare_settings, selected


def main():
    options = parser(__doc__)
    options.add_argument("--validate-only", action="store_true",
                         help="Validate configuration without a Docker daemon or writes.")
    args = options.parse_args()
    services = selected(args)
    if not args.validate_only:
        prepare_settings(services)
    config = configuration()
    for name in services:
        service = config["services"][name]
        env = service["environment"]
        if not env.get("GOOGLE_OAUTH_CLIENT_ID", "").endswith(".apps.googleusercontent.com"):
            raise RuntimeError("Set MCP_GOOGLE_OAUTH_CLIENT_ID once in the central .env.")
        if len(env.get("FASTMCP_SERVER_AUTH_GOOGLE_JWT_SIGNING_KEY", "")) < 32:
            raise RuntimeError(f"{name}: run 01-prepare.py to generate a signing key.")
        if env.get("GOOGLE_OAUTH_CLIENT_SECRET"):
            raise RuntimeError(f"{name}: the Google client secret belongs in the external client.")
        source = Path(service["volumes"][0]["source"])
        if not source.is_absolute():
            raise RuntimeError("BASE_PATH must be absolute.")
    if args.validate_only:
        print("Selected MCP settings and Compose validated; runtime not checked.")
        return
    network = config["networks"]["redlocal"]["name"]
    result = subprocess.run(["docker", "network", "inspect", network],
                            capture_output=True, text=True, check=False)
    if result.returncode or json.loads(result.stdout)[0]["Driver"] != "bridge":
        raise RuntimeError("An existing bridge redlocal network and running Docker daemon are required.")
    for name in services:
        service = config["services"][name]
        uid, gid = (int(value) for value in service["user"].split(":"))
        if os.getuid() != 0 and (uid, gid) != (os.getuid(), os.getgid()):
            raise RuntimeError("Run preparation as root or as the configured MCP_UID/MCP_GID.")
        data = Path(service["volumes"][0]["source"])
        for path in (data, data / "credentials", data / "attachments"):
            existed = path.exists()
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not existed and os.getuid() == 0:
                os.chown(path, uid, gid)
            if path.stat().st_uid != uid:
                raise RuntimeError(f"{name}: data directory has a different owner.")
            path.chmod(0o700)
        print(f"{name}: prepared.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(str(error))
