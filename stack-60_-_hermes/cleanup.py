#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Controlled cleanup of Hermes and its sandbox runtime."""

import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
from pathlib import Path

from stack_env import load_env


STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"
LOCK_FILE = STACK_DIR / ".lock"
RUNTIME_ALLOWED = {
    "BROWSERBASE_ADVANCED_STEALTH", "BROWSERBASE_PROXIES", "BROWSER_INACTIVITY_TIMEOUT",
    "BROWSER_SESSION_TIMEOUT", "IMAGE_TOOLS_DEBUG", "MOA_TOOLS_DEBUG",
    "TERMINAL_LIFETIME_SECONDS", "TERMINAL_MODAL_IMAGE", "TERMINAL_TIMEOUT",
    "VISION_TOOLS_DEBUG", "WEB_TOOLS_DEBUG",
}
RUNTIME_KEYS = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")
RUNTIME_ARTIFACTS = (
    "config.yaml", ".hermes", "gateway.pid", "gateway.lock", "gateway_state.json",
    "gateway-starts.log", "models_dev_cache.json", "tui-theme-boot.json", "processes.json",
    "active_profile", ".update_check", "errors.log", "image_cache", "audio_cache",
    "document_cache", "browser_screenshots", "checkpoints", "sandboxes", "logs",
)
USAGE = """Usage:
  ./cleanup.py [--dry-run]
  ./cleanup.py --reset-sandbox [--dry-run] [--yes]
  ./cleanup.py --reset-state [--dry-run] [--yes]
  ./cleanup.py --factory-reset [--dry-run] [--yes]

Options:
  --reset-sandbox  Destroy only sandbox workspace + lifecycle state.db generation.
                   Intended as the fast repair path for corrupted sandbox state.
  --reset-state    Also remove Hermes auth/session/routing databases and state.
  --factory-reset  Remove all mutable Hermes state and sandbox workspace/home.
                   Preserves managed config/ and Hermes data/bin/.
  --dry-run        Show exactly what would be removed.
  --yes            Skip interactive confirmation for destructive modes.
  -h, --help       Show this help."""


def log(message: str) -> None:
    """Print a cleanup progress message."""
    print(f"[cleanup] {message}")


def warn(message: str) -> None:
    """Print a cleanup warning to stderr."""
    print(f"[cleanup] WARNING: {message}", file=sys.stderr)


def die(message: str) -> None:
    """Report a cleanup error and exit."""
    print(f"[cleanup] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def present(path: Path) -> bool:
    """Check for a path, including a dangling symlink."""
    return path.exists() or path.is_symlink()


def children(path: Path) -> list[Path]:
    """List immediate children of a real directory without following symlinks."""
    if not path.is_dir() or path.is_symlink():
        return []
    with os.scandir(path) as entries:
        return [Path(entry.path) for entry in entries]


class Cleanup:
    """Validate cleanup scope and execute the selected cleanup mode."""
    def __init__(self, mode: str, dry_run: bool, assume_yes: bool):
        """Load cleanup settings and reject unsafe paths or running containers."""
        self.mode = mode
        self.dry_run = dry_run
        self.assume_yes = assume_yes
        self.env_hash = sha256(ENV_FILE)
        env = load_env(ENV_FILE)
        for key in ("BASE_PATH", "HERMES_SERVICE", "SANDBOX_SERVICE", "HERMES_CONTAINER", "SANDBOX_CONTAINER"):
            if not env.get(key):
                die(f"Required variable {key} is missing/empty in .env")
        self.env = env
        for key in ("HERMES_SERVICE", "SANDBOX_SERVICE"):
            service = env[key]
            if "/" in service:
                die(f"{key} must be a directory name, not a path.")
            if not service.startswith("service_-_"):
                die(f"Unexpected {key}: {service}")
        self.base = Path(os.path.realpath(env["BASE_PATH"]))
        self.hermes_root = Path(os.path.realpath(self.base / env["HERMES_SERVICE"]))
        self.sandbox_root = Path(os.path.realpath(self.base / env["SANDBOX_SERVICE"]))
        self.hermes_data = self.hermes_root / "data"
        self.hermes_config = self.hermes_root / "config"
        self.hermes_logs = self.hermes_root / "logs"
        self.sandbox_data = self.sandbox_root / "data"
        self.sandbox_config = self.sandbox_root / "config"
        self.sandbox_logs = self.sandbox_root / "logs"
        self.sandbox_home = self.sandbox_data / "home"
        self.sandbox_workspace = self.sandbox_data / "workspace"
        self.sandbox_state = self.sandbox_data / "state"
        for root in (self.hermes_root, self.sandbox_root):
            if not str(root).startswith(str(self.base) + "/service_-_"):
                die(f"Unsafe service path resolved outside expected service_-_* tree: {root}")
            if root == self.base or root == Path("/"):
                die(f"Unsafe cleanup path: {root}")
        if mode != "reset-sandbox" and LOCK_FILE.exists():
            die(f"Refusing cleanup while {LOCK_FILE} exists. Stop the stack and remove .lock deliberately first.")
        for key in ("HERMES_CONTAINER", "SANDBOX_CONTAINER"):
            if self.container_running(env[key]):
                die(f"Container {env[key]} is still running. Stop {'Hermes' if key == 'HERMES_CONTAINER' else 'it'} first.")
        cleaner = env.get("SANDBOX_CLEANUP_CONTAINER") or "hermes-sandbox-cleanup"
        if self.container_running(cleaner):
            die(f"Container {cleaner} is still running. Stop it first.")

    @staticmethod
    def container_running(name: str) -> bool:
        """Check whether Docker reports a container as running."""
        result = subprocess.run(["docker", "inspect", name], capture_output=True, check=False)
        if result.returncode:
            return False
        result = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name],
                                capture_output=True, text=True, check=False)
        return result.returncode == 0 and result.stdout.strip() == "true"

    def assert_within(self, path: Path) -> None:
        """Reject paths whose resolved location lies outside the service trees."""
        resolved = Path(os.path.realpath(path))
        if not any(resolved == root or root in resolved.parents for root in (self.hermes_root, self.sandbox_root)):
            die(f"Refusing to touch path outside Hermes service trees: {resolved}")

    def audit_runtime_env_safety(self) -> None:
        """Reject runtime env symlinks and stack-managed variable overrides."""
        runtime_env = self.hermes_data / ".env"
        if not present(runtime_env):
            return
        if runtime_env.is_symlink():
            die(f"Runtime .env must not be a symlink: {runtime_env}")
        if not runtime_env.is_file():
            die(f"Runtime .env is not a regular file: {runtime_env}")
        managed = ENV_FILE.read_text().splitlines()
        for line in runtime_env.read_text().splitlines():
            match = RUNTIME_KEYS.match(line)
            if match and match.group(1) not in RUNTIME_ALLOWED:
                key = match.group(1)
                if any(entry.startswith(f"{key}=") for entry in managed):
                    die(f"Runtime .env redefines stack-managed variable: {key}")

    def remove_path(self, path: Path) -> None:
        """Remove one scoped path unless this is a dry run."""
        # Resolve the target again at deletion time so cleanup stays inside service roots.
        self.assert_within(path)
        if not present(path):
            return
        print(f"  REMOVE  {path}")
        if self.dry_run:
            return
        result = subprocess.run(["rm", "-rf", "--one-file-system", "--", str(path)],
                                stderr=subprocess.DEVNULL, check=False)
        if result.returncode:
            subprocess.run(["rm", "-rf", "--", str(path)], check=True)

    def wipe_contents(self, path: Path) -> None:
        """Remove the immediate contents of a scoped directory."""
        self.assert_within(path)
        for child in children(path):
            self.remove_path(child)

    def cleanup_runtime(self) -> None:
        """Remove shadow configuration and transient Hermes runtime artifacts."""
        log("Removing shadow configuration and stale runtime artifacts.")
        self.audit_runtime_env_safety()
        for name in RUNTIME_ARTIFACTS:
            self.remove_path(self.hermes_data / name)

    def reset_sandbox(self) -> None:
        """Clear the workspace and lifecycle state for a new sandbox generation."""
        log("Resetting sandbox generation: workspace + lifecycle state.")
        self.wipe_contents(self.sandbox_workspace)
        self.wipe_contents(self.sandbox_state)
        if not self.dry_run:
            uid = self.env.get("SANDBOX_UID") or "1000"
            gid = self.env.get("SANDBOX_GID") or "1000"
            subprocess.run(["install", "-d", "-m", "0750", "-o", uid, "-g", gid,
                            str(self.sandbox_workspace)], check=True)
            subprocess.run(["install", "-d", "-m", "0700", "-o", "0", "-g", "0",
                            str(self.sandbox_state)], check=True)
        for path in (self.sandbox_home, self.sandbox_config, self.hermes_data):
            print(f"  KEEP    {path}")
        log("Next sandbox boot will create a new generation and state.db.")

    def cleanup_state(self) -> None:
        """Remove runtime artifacts plus Hermes auth, session, and routing state."""
        self.cleanup_runtime()
        log("Removing Hermes auth/session/routing state.")
        for name in ("auth.json", "auth.lock"):
            self.remove_path(self.hermes_data / name)
        for pattern in ("state.db*", "hermes_state.db*", "response_store.db*"):
            for match in sorted(glob.glob(str(self.hermes_data / pattern))):
                self.remove_path(Path(match))
        for name in ("sessions", "sessions.json", "channel_directory.json"):
            self.remove_path(self.hermes_data / name)

    def factory_reset(self) -> None:
        """Clear mutable Hermes and sandbox state while retaining managed config and binaries."""
        log("Factory reset: removing all mutable Hermes data except data/bin/.")
        for child in children(self.hermes_data):
            if child.name == "bin":
                print(f"  KEEP    {child}")
            else:
                self.remove_path(child)
        log("Factory reset: clearing Hermes logs.")
        self.wipe_contents(self.hermes_logs)
        log("Factory reset: clearing sandbox mutable home/workspace/state.")
        for path in (self.sandbox_home, self.sandbox_workspace, self.sandbox_state):
            self.wipe_contents(path)
        log("Factory reset: clearing sandbox logs.")
        self.wipe_contents(self.sandbox_logs)
        print()
        for path in (self.hermes_config, self.sandbox_config, self.hermes_data / "bin"):
            print(f"  KEEP    {path}")

    def confirm(self) -> None:
        """Require explicit interactive confirmation for destructive modes."""
        if self.mode == "runtime" or self.assume_yes or self.dry_run:
            return
        if not sys.stdin.isatty():
            die(f"Mode {self.mode} requires --yes when stdin is not interactive.")
        print()
        warn(f"Mode '{self.mode}' is destructive.")
        if self.mode == "reset-sandbox":
            warn("Sandbox workspace and lifecycle SQLite state will be erased.")
            warn("Sandbox home/SSH identity, Hermes state and Git-backed memory are preserved.")
        elif self.mode == "reset-state":
            warn("Pairing, home-channel routing, provider auth and session history will be reset.")
        else:
            warn("All mutable Hermes data, logs, sandbox home/workspace/state will be erased.")
            warn("Managed config/ directories and Hermes data/bin/ will be preserved.")
        try:
            answer = input("Type CLEAN to continue: ")
        except EOFError:
            raise SystemExit(1) from None
        if answer != "CLEAN":
            die("Cancelled.")

    def audit(self) -> None:
        """Verify the selected cleanup mode's expected filesystem state."""
        if self.dry_run:
            return
        failures = []
        if sha256(ENV_FILE) != self.env_hash:
            failures.append(f"stack .env changed during cleanup: {ENV_FILE}")
        if self.mode == "reset-sandbox":
            for path in (self.sandbox_workspace, self.sandbox_state):
                if children(path):
                    failures.append(f"sandbox reset directory is not empty: {path}")
        else:
            for name in (".hermes", "config.yaml", "gateway.pid", "gateway.lock",
                         "gateway_state.json", "models_dev_cache.json"):
                path = self.hermes_data / name
                if present(path):
                    failures.append(f"still exists: {path}")
            self.audit_runtime_env_safety()
        if self.mode == "reset-state":
            for name in ("auth.json", "state.db", "sessions"):
                path = self.hermes_data / name
                if present(path):
                    failures.append(f"still exists: {path}")
        if self.mode == "factory-reset":
            for child in children(self.hermes_data):
                if child.name != "bin":
                    failures.append(f"unexpected Hermes data remains: {child}")
            for path in (self.hermes_logs, self.sandbox_home, self.sandbox_workspace,
                         self.sandbox_state, self.sandbox_logs):
                if children(path):
                    failures.append(f"directory is not empty: {path}")
        for failure in failures:
            print(f"[cleanup] AUDIT FAIL: {failure}", file=sys.stderr)
        if failures:
            die("Post-cleanup audit failed.")
        log("Post-cleanup audit: OK")

    def execute(self) -> None:
        """Show the cleanup plan, perform the selected mode, and audit it."""
        print()
        log("Hermes cleanup plan")
        for label, value in (
            ("MODE", self.mode), ("DRY_RUN", int(self.dry_run)), ("STACK", STACK_DIR),
            ("HERMES", self.hermes_root), ("SANDBOX", self.sandbox_root),
            ("PRESERVE", self.hermes_config), ("PRESERVE", self.sandbox_config),
            ("PRESERVE", self.hermes_data / "bin"),
        ):
            print(f"  {label:<11} {value}")
        print()
        self.confirm()
        {"runtime": self.cleanup_runtime, "reset-sandbox": self.reset_sandbox,
         "reset-state": self.cleanup_state, "factory-reset": self.factory_reset}[self.mode]()
        self.audit()
        print()
        log("Dry-run complete. Nothing was removed." if self.dry_run else "Cleanup complete.")


def main(args: list[str]) -> None:
    """Parse cleanup options, validate prerequisites, and run the selected mode."""
    mode = "runtime"
    dry_run = False
    assume_yes = False
    for arg in args:
        if arg in ("--reset-sandbox", "--reset-state", "--factory-reset"):
            if mode != "runtime":
                die("Choose only one cleanup mode.")
            mode = arg[2:]
        elif arg == "--dry-run":
            dry_run = True
        elif arg == "--yes":
            assume_yes = True
        elif arg in ("-h", "--help"):
            print(USAGE)
            return
        else:
            die(f"Unknown argument: {arg}")
    if os.geteuid() != 0:
        die("Must be run as root.")
    for command in ("docker", "realpath", "find", "rm", "stat", "grep", "basename", "id",
                    "sha256sum", "awk", "install"):
        if shutil.which(command) is None:
            die(f"Required command not found: {command}")
    if not ENV_FILE.is_file():
        die(f"Missing {ENV_FILE}")
    Cleanup(mode, dry_run, assume_yes).execute()


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from None
    except (OSError, ValueError) as error:
        die(str(error))
