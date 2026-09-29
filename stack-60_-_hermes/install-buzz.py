#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Install the pinned Buzz CLI into Hermes persistent runtime data.

The script builds or copies the expected Buzz artifact, checks required
paths and permissions, and installs it without relying on a transient
container filesystem. It is an optional post-preparation integration;
importing this module does not download or install software."""

import os
import re
import shutil
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
import tempfile
from pathlib import Path

if __package__:
    from .stack_env import load_env
else:
    from stack_env import load_env


STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"
DOCKERFILE = STACK_DIR / "config/buzz/Dockerfile"
SOURCE_REPOSITORY = "https://github.com/block/buzz.git"
SOURCE_REF = "78618804ec86a014524ad7d1fb55928e8f5c3edf"
CONTAINER_PATH = "/opt/data/bin/buzz"


def fail(message: str) -> None:
    """Report a Buzz installation error and exit."""
    print(f"[buzz-prepare] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(*args: str, quiet: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a stack-local command, optionally suppressing output or nonzero failure."""
    return subprocess.run(args, cwd=STACK_DIR, text=True, stdout=subprocess.DEVNULL if quiet else None,
                          stderr=subprocess.DEVNULL if quiet else None, check=check)


def regular(path: Path) -> bool:
    """Check that a path is a nonsymlink regular file."""
    return path.is_file() and not path.is_symlink()


def main() -> None:
    """Install and validate the pinned Buzz binary in Hermes persistent data."""
    if os.geteuid() != 0:
        fail("run as root")
    if not ENV_FILE.is_file():
        fail(f"missing {ENV_FILE}")
    if not DOCKERFILE.is_file():
        fail(f"missing {DOCKERFILE}")
    for command in ("docker", "install"):
        if shutil.which(command) is None:
            fail(f"missing required command: {command}")
    if run("docker", "version", quiet=True, check=False).returncode:
        fail("Docker is unavailable")
    env = load_env(ENV_FILE)
    for key in ("BASE_PATH", "HERMES_SERVICE", "HERMES_UID", "HERMES_GID", "HERMES_IMAGE", "HERMES_VERSION"):
        if not env.get(key):
            fail(f"missing {key} in {ENV_FILE}")
    base = env["BASE_PATH"]
    service = env["HERMES_SERVICE"]
    if not base.startswith("/") or base == "/":
        fail("BASE_PATH must be an absolute non-root path")
    if re.fullmatch(r"service_-_[A-Za-z0-9._-]+", service) is None:
        fail("unsafe HERMES_SERVICE")
    if (env.get("BUZZ_CLI_PATH") or CONTAINER_PATH) != CONTAINER_PATH:
        fail(f"BUZZ_CLI_PATH must be empty or {CONTAINER_PATH}")
    if env["HERMES_VERSION"] == "latest":
        fail("HERMES_VERSION cannot be latest")
    bin_dir = Path(base.rstrip("/")) / service / "data/bin"
    buzz = bin_dir / "buzz"
    provenance = bin_dir / ".buzz-source"
    expected = f"{SOURCE_REPOSITORY}@{SOURCE_REF}"
    image = f"local-hybrid-ai-buzz-cli:{SOURCE_REF[:12]}"
    container = f"local-hybrid-ai-buzz-extract-{SOURCE_REF[:12]}-{os.getpid()}"
    uid, gid = env["HERMES_UID"], env["HERMES_GID"]
    run("install", "-d", "-m", "0750", "-o", uid, "-g", gid, str(bin_dir))

    def validates(container_binary: str) -> bool:
        """Check whether a Buzz binary runs inside the configured Hermes image."""
        return run("docker", "run", "--rm", "--network", "none", "--read-only",
                   "-v", f"{bin_dir}:/opt/data/bin:ro", "--entrypoint", container_binary,
                   f"{env['HERMES_IMAGE']}:{env['HERMES_VERSION']}", "--help",
                   quiet=True, check=False).returncode == 0

    try:
        if regular(buzz) and os.access(buzz, os.X_OK) and regular(provenance):
            if provenance.read_text().rstrip("\n") == expected and validates(CONTAINER_PATH):
                for path in (buzz, provenance):
                    os.chown(path, int(uid), int(gid))
                os.chmod(buzz, 0o755)
                os.chmod(provenance, 0o640)
                print("[buzz-prepare] Buzz CLI already matches pinned source and runs inside Hermes image")
                return
        print(f"[buzz-prepare] building Buzz CLI from pinned source {SOURCE_REF}")
        run("docker", "build", "--build-arg", f"BUZZ_SOURCE_REPOSITORY={SOURCE_REPOSITORY}",
            "--build-arg", f"BUZZ_SOURCE_REF={SOURCE_REF}", "-t", image, "-f", str(DOCKERFILE),
            str(STACK_DIR / "config/buzz"), quiet=True)
        run("docker", "create", "--name", container, image, quiet=True)
        with tempfile.TemporaryDirectory(prefix=".buzz-install.", dir=bin_dir) as temporary:
            extracted = Path(temporary) / "buzz"
            run("docker", "cp", f"{container}:/usr/local/bin/buzz", str(extracted))
            if not regular(extracted) or extracted.stat().st_size == 0:
                fail("builder did not produce a regular non-empty buzz binary")
            new_binary = bin_dir / f".buzz.new.{os.getpid()}"
            new_provenance = bin_dir / f".buzz-source.new.{os.getpid()}"
            run("install", "-m", "0755", "-o", uid, "-g", gid, str(extracted), str(new_binary))
            new_provenance.write_text(expected + "\n")
            os.chown(new_provenance, int(uid), int(gid))
            os.chmod(new_provenance, 0o640)
            if not validates(f"/opt/data/bin/{new_binary.name}"):
                fail(f"compiled Buzz CLI does not run inside {env['HERMES_IMAGE']}:{env['HERMES_VERSION']}")
            os.replace(new_binary, buzz)
            os.replace(new_provenance, provenance)
        if not regular(buzz) or not os.access(buzz, os.X_OK):
            fail("Buzz CLI installation failed")
        metadata = buzz.stat()
        if (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)) != (int(uid), int(gid), 0o755):
            fail("Buzz CLI ownership/mode is incorrect")
        if provenance.read_text().rstrip("\n") != expected:
            fail("Buzz CLI provenance mismatch")
        if not validates(CONTAINER_PATH):
            fail("installed Buzz CLI failed final Hermes-image validation")
        print(f"[buzz-prepare] Buzz CLI ready at {buzz}")
        print("[buzz-prepare] Buzz remains optional at runtime; the binary is always pre-provisioned")
    finally:
        run("docker", "rm", "-f", container, quiet=True, check=False)
        run("docker", "image", "rm", image, quiet=True, check=False)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        fail(str(error))
