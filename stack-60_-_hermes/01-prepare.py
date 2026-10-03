#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Prepare and audit the Hermes agent runtime before container startup.

The entrypoint validates environment values, prerequisite stack locks,
runtime directory ownership, keys, and deployed configuration. It refuses
unsafe changes to an existing runtime and writes the Hermes preparation
lock only after its audit succeeds. Optional integrations are handled by
separate scripts. Importing the module does not perform preparation."""

import hashlib
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
LOCK_FILE = STACK_DIR / ".lock"
ALL_KEYS = """STACKS_ROOT BASE_PATH NETWORK_NAME TZ HERMES_SERVICE HERMES_MEMORY_SERVICE MEMORY_SYNC_SERVICE SANDBOX_SERVICE
HERMES_CONTAINER MEMORY_SYNC_CONTAINER SANDBOX_CONTAINER SANDBOX_CLEANUP_CONTAINER
HERMES_IMAGE HERMES_VERSION SANDBOX_IMAGE MEMORY_SYNC_IMAGE SANDBOX_CLEANUP_IMAGE HERMES_UID HERMES_GID
HERMES_MODEL LITELLM_BASE_URL LITELLM_API_KEY LITELLM_MCP_URL LITELLM_MCP_API_KEY TELEGRAM_BOT_TOKEN TELEGRAM_ALLOWED_USERS
HERMES_DASHBOARD HERMES_DASHBOARD_HOST API_SERVER_ENABLED API_SERVER_HOST API_SERVER_PORT API_SERVER_KEY
API_SERVER_MODEL_NAME API_SERVER_CORS_ORIGINS SEARXNG_URL FIRECRAWL_API_URL FIRECRAWL_API_KEY
TERMINAL_SSH_HOST TERMINAL_SSH_USER TERMINAL_SSH_PORT TERMINAL_SSH_KEY TERMINAL_SSH_PERSISTENT TERMINAL_TIMEOUT
SANDBOX_UID SANDBOX_GID SANDBOX_CPU SANDBOX_MEMORY SANDBOX_PIDS SANDBOX_SHM_SIZE
MEMORY_SYNC_INTERVAL_SECONDS GITMEM_REPOSITORY GITMEM_BRANCH SANDBOX_CLEANUP_RETENTION_DAYS
SANDBOX_CLEANUP_QUARANTINE_DAYS SANDBOX_CLEANUP_DB_RETENTION_DAYS SANDBOX_CLEANUP_SWEEP_HOUR
SANDBOX_CLEANUP_SWEEP_MINUTE""".split()
OPTIONAL_EMPTY = {"TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS", "API_SERVER_CORS_ORIGINS", "SEARXNG_URL", "FIRECRAWL_API_URL",
                  "FIRECRAWL_API_KEY", "GITMEM_REPOSITORY", "GITMEM_BRANCH"}
RUNTIME_ALLOWED = {
    "BROWSERBASE_ADVANCED_STEALTH", "BROWSERBASE_PROXIES", "BROWSER_INACTIVITY_TIMEOUT",
    "BROWSER_SESSION_TIMEOUT", "IMAGE_TOOLS_DEBUG", "MOA_TOOLS_DEBUG", "TERMINAL_LIFETIME_SECONDS",
    "TERMINAL_MODAL_IMAGE", "TERMINAL_TIMEOUT", "VISION_TOOLS_DEBUG", "WEB_TOOLS_DEBUG",
}
RUNTIME_KEY = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")
MODEL_REFERENCE = "${HERMES_MODEL}"


def log(message: str) -> None:
    """Print an indented preparation message."""
    print(f"  {message}")


def step(message: str) -> None:
    """Print a preparation section heading."""
    print(f"\n== {message}")


def warn(message: str) -> None:
    """Print a preparation warning to stderr."""
    print(f"  WARNING: {message}", file=sys.stderr)


def die(message: str) -> None:
    """Report a preparation error and exit."""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def present(path: Path) -> bool:
    """Check for a path, including a dangling symlink."""
    return path.exists() or path.is_symlink()


def model_default(text: str) -> str:
    """Extract the default model from the model section of YAML text."""
    in_model = False
    for line in text.splitlines():
        if re.fullmatch(r"model:\s*", line):
            in_model = True
            continue
        if in_model and line and not line[0].isspace():
            break
        if in_model:
            match = re.match(r"\s+default:\s*(.*)", line)
            if match:
                return match.group(1)
    return ""


def tree_entries(root: Path, recursive: bool) -> list[str]:
    """List immediate or recursive entries relative to a root."""
    if not recursive:
        return sorted(child.name for child in root.iterdir())
    return sorted(str(child.relative_to(root)) for child in root.rglob("*"))


class Prepare:
    """Validate, provision, and audit a stopped Hermes stack."""
    def __init__(self):
        """Validate stack settings and derive managed persistent paths."""
        self.env_hash = sha256(ENV_FILE)
        step("Read-only .env validation")
        lines = ENV_FILE.read_text().splitlines()
        for key in ALL_KEYS:
            if not any(line.startswith(f"{key}=") for line in lines):
                die(f"missing {key} in .env")
        self.env = load_env(ENV_FILE)
        for key in ALL_KEYS:
            if key in OPTIONAL_EMPTY:
                continue
            value = self.env.get(key, "")
            if not value:
                die(f"{key} is empty in .env")
            if value.startswith("CHANGE_ME"):
                die(f"{key} is still unset: {value}")
            if value.startswith("PUT_YOUR_"):
                die(f"{key} still uses a placeholder: {value}")
        env = self.env
        if len(env["API_SERVER_KEY"]) < 8:
            die("API_SERVER_KEY must contain at least 8 characters")
        if len(env["LITELLM_MCP_API_KEY"]) < 8:
            die("LITELLM_MCP_API_KEY must contain at least 8 characters")
        if env["HERMES_VERSION"] == "latest":
            die("HERMES_VERSION cannot be latest")
        if env["HERMES_IMAGE"].endswith(":latest"):
            die("HERMES_IMAGE cannot use :latest")
        if not re.fullmatch(r"https?://\S+/mcp/?", env["LITELLM_MCP_URL"]):
            die("LITELLM_MCP_URL must be an HTTP(S) endpoint ending in /mcp")
        token = env.get("TELEGRAM_BOT_TOKEN", "")
        if token:
            if token.startswith("CHANGE_ME"):
                die("TELEGRAM_BOT_TOKEN is still unset")
            if token.startswith("PUT_YOUR_"):
                die("TELEGRAM_BOT_TOKEN still uses a placeholder")
            if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]{30,}", token):
                die("TELEGRAM_BOT_TOKEN does not match the expected BotFather format")
            if not re.fullmatch(r"[1-9][0-9]*(?:,[1-9][0-9]*)*", env.get("TELEGRAM_ALLOWED_USERS", "")):
                die("TELEGRAM_ALLOWED_USERS must list numeric user IDs when Telegram is enabled")
        for key in ("STACKS_ROOT", "BASE_PATH"):
            if not env[key].startswith("/"):
                die(f"{key} must be an absolute path")
            env[key] = env[key][:-1] if env[key].endswith("/") else env[key]
            if not env[key]:
                die(f"{key} cannot be /")
        if str(STACK_DIR) != f"{env['STACKS_ROOT']}/stack-60_-_hermes":
            die(f"Stack 60 must be at {env['STACKS_ROOT']}/stack-60_-_hermes; current path: {STACK_DIR}")
        for number, name in ((0, "platform"), (3, "litellm")):
            lock = Path(env["STACKS_ROOT"]) / f"stack-{number * 10:02d}_-_{name}" / ".lock"
            if not lock.is_file():
                die(f"Stack {number * 10:02d} is not prepared: missing {lock}")
        for key in ("HERMES_SERVICE", "HERMES_MEMORY_SERVICE", "MEMORY_SYNC_SERVICE", "SANDBOX_SERVICE"):
            if not re.fullmatch(r"service_-_[A-Za-z0-9._-]+", env[key]):
                die(f"{key} must match service_-_*")
        for first, second in (("HERMES_SERVICE", "SANDBOX_SERVICE"),
                              ("HERMES_SERVICE", "HERMES_MEMORY_SERVICE"),
                              ("SANDBOX_SERVICE", "HERMES_MEMORY_SERVICE")):
            if env[first] == env[second]:
                die(f"{first} and {second} must differ")
        base = Path(env["BASE_PATH"])
        self.hermes_root = base / env["HERMES_SERVICE"]
        self.memory_root = base / env["HERMES_MEMORY_SERVICE"]
        self.memory_data = self.memory_root / "data"
        self.sandbox_root = base / env["SANDBOX_SERVICE"]
        self.hermes_config = self.hermes_root / "config"
        self.hermes_data = self.hermes_root / "data"
        self.hermes_logs = self.hermes_root / "logs"
        self.sandbox_config = self.sandbox_root / "config"
        self.sandbox_data = self.sandbox_root / "data"
        self.sandbox_logs = self.sandbox_root / "logs"
        self.ssh_private = self.hermes_config / "ssh/hermes_executor_ed25519"
        self.ssh_public = Path(f"{self.ssh_private}.pub")
        self.authorized_keys = self.sandbox_data / "home/.ssh/authorized_keys"
        self.host_private = self.sandbox_config / "ssh-host/ssh_host_ed25519_key"
        self.host_public = Path(f"{self.host_private}.pub")
        log(".env is complete and unchanged")
        log(f"Hermes image pinned to {env['HERMES_IMAGE']}:{env['HERMES_VERSION']}")
        log(f"External memory directory: {self.memory_data}")
        log(f"MCP gateway: {env['LITELLM_MCP_URL']}")
        log("Telegram: enabled; token format is valid" if token else
            "Telegram: disabled; TELEGRAM_BOT_TOKEN is empty")

    def run(self, *args: str, capture: bool = False, quiet: bool = False,
            check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run a command in the stack directory with the validated environment."""
        return subprocess.run(args, cwd=STACK_DIR, env=self.env, text=True, check=check,
                              stdout=subprocess.PIPE if capture else subprocess.DEVNULL if quiet else None,
                              stderr=subprocess.DEVNULL if quiet else None)

    def sources(self) -> None:
        """Validate required sources and managed model references."""
        step("Stack source files")
        self.config_source = STACK_DIR / "config/hermes/config.yaml"
        self.sandbox_dockerfile = STACK_DIR / "config/sandbox/Dockerfile"
        self.sandbox_entrypoint = STACK_DIR / "config/sandbox/entrypoint.sh"
        sources = (
            self.config_source, self.sandbox_dockerfile, self.sandbox_entrypoint,
            STACK_DIR / "config/sandbox/state-init.py", STACK_DIR / "config/sandbox-cleanup/Dockerfile",
            STACK_DIR / "config/sandbox-cleanup/cleanup.py", STACK_DIR / "config/memory-sync/Dockerfile",
            STACK_DIR / "config/memory-sync/entrypoint.sh",
            STACK_DIR / "config/memory-sync/hermes-memory-sync.sh",
        )
        for source in sources:
            if not source.is_file() or source.stat().st_size == 0:
                die(f"missing or empty source file: {source}")
        text = self.config_source.read_text()
        for key in ("HERMES_MODEL", "LITELLM_MCP_URL", "LITELLM_MCP_API_KEY"):
            if "${" + key + "}" not in text:
                die(f"config/hermes/config.yaml must contain ${{{key}}}")
        model = self.env["HERMES_MODEL"]
        if not re.fullmatch(r"[A-Za-z0-9._:/+@-]+", model):
            die(f"HERMES_MODEL contains characters that cannot be rendered safely: {model}")
        if model_default(text) != MODEL_REFERENCE:
            die("model.default in config/hermes/config.yaml must be ${HERMES_MODEL}")
        for line in text.splitlines():
            match = re.match(r"\s+model:\s+(.+)", line)
            if match and match.group(1) != MODEL_REFERENCE:
                die(f"hard-coded model reference in config/hermes/config.yaml: {match.group(1)}")
        summary = next((match.group(1) for line in text.splitlines()
                        if (match := re.match(r"\s*summary_model:\s*(.*)", line))), "")
        if summary and summary != MODEL_REFERENCE:
            die("compression.summary_model must be ${HERMES_MODEL}")
        if re.search(r"(^|\s)(install|chown|chmod)(\s|$)|hermes_authorized_key|AUTHORIZED_SOURCE",
                     self.sandbox_entrypoint.read_text(), re.MULTILINE):
            die("entrypoint.sh contains obsolete preparation logic; refusing to install")
        log("Source files are present and consistent")

    def docker_preflight(self) -> None:
        """Require the shared bridge network and stopped Hermes containers."""
        name = self.env["NETWORK_NAME"]
        step(f"Docker network {name}")
        if self.run("docker", "network", "inspect", name, quiet=True, check=False).returncode:
            die(f"missing shared network {name}; Stack 00 must create it")
        driver = self.run("docker", "network", "inspect", "-f", "{{.Driver}}", name, capture=True).stdout.strip()
        if driver != "bridge":
            die(f"network {name} uses driver '{driver}', not bridge")
        log("Network exists, uses bridge, and remains managed by Stack 00")
        step("Hermes status")
        for container in (self.env["HERMES_CONTAINER"], self.env["SANDBOX_CONTAINER"]):
            if self.run("docker", "inspect", container, quiet=True, check=False).returncode == 0:
                running = self.run("docker", "inspect", "-f", "{{.State.Running}}", container,
                                   capture=True).stdout.strip()
                if running == "true":
                    die(f"container '{container}' is still running; run ./local-ai stack-60 stop first")
                log(f"{container}: stopped")
            else:
                log(f"{container}: absent")

    def persistent_filesystem(self) -> None:
        """Verify bootstrapped directories and preserve or create memory files."""
        step("Target directory creation and verification")
        paths = (self.hermes_root, self.hermes_config, self.hermes_config / "ssh", self.hermes_data,
                 self.hermes_logs, self.memory_root, self.memory_data, self.sandbox_root,
                 self.sandbox_config, self.sandbox_config / "ssh-host", self.sandbox_data,
                 self.sandbox_data / "home", self.sandbox_data / "home/.ssh",
                 self.sandbox_data / "workspace", self.sandbox_data / "state", self.sandbox_logs)
        for path in paths:
            if not path.is_dir() or path.is_symlink():
                die(f"missing {path}; run ./local-ai stack-60 install to create service directories")
        uid, gid = self.env["HERMES_UID"], self.env["HERMES_GID"]
        for name in ("MEMORY.md", "USER.md"):
            path = self.memory_data / name
            if path.exists():
                if not path.is_file() or path.is_symlink():
                    die(f"{path} must be a regular file")
                log(f"Existing memory file preserved: {name}")
            else:
                self.run("install", "-m", "0640", "-o", uid, "-g", gid, "/dev/null", str(path))
                log(f"Initial local memory file created: {name}")
            self.run("chown", f"{uid}:{gid}", str(path))
            self.run("chmod", "0640", str(path))
        log(f"{self.hermes_root}/{{config,data,logs}}")
        log(f"{self.memory_data}: persistent local memory")
        log(f"{self.sandbox_root}/{{config,data,logs}}")
        log("Existing data/, logs/, workspace, memory, and data/bin are preserved")
        log("Git memory sync is optional and not part of the minimal Stack 60 install")

    def audit_shadow(self) -> None:
        """Reject shadow config and runtime overrides of managed environment keys."""
        runtime_env = self.hermes_data / ".env"
        runtime_config = self.hermes_data / "config.yaml"
        shadow = self.hermes_data / ".hermes"
        if present(shadow):
            die(f"shadow configuration detected: {shadow}; review cleanup.py")
        if runtime_config.is_symlink():
            die(f"shadow configuration symlink detected: {runtime_config}; review cleanup.py")
        if runtime_config.exists():
            if not runtime_config.is_file():
                die(f"invalid shadow configuration: {runtime_config}; review cleanup.py")
            if runtime_config.stat().st_size:
                die(f"active, nonempty shadow configuration: {runtime_config}; review cleanup.py")
            warn("empty data/config.yaml is allowed; the managed bind mount hides it")
        if runtime_env.is_symlink():
            die(f"runtime .env cannot be a symlink: {runtime_env}")
        if runtime_env.exists():
            if not runtime_env.is_file():
                die(f"runtime .env is not a regular file: {runtime_env}")
            managed = ENV_FILE.read_text().splitlines()
            for line in runtime_env.read_text().splitlines():
                match = RUNTIME_KEY.match(line)
                if match and match.group(1) not in RUNTIME_ALLOWED:
                    key = match.group(1)
                    if any(entry.startswith(f"{key}=") for entry in managed):
                        die(f"runtime .env attempts to override a stack-managed variable: {key}")
            log("data/.env is allowed; it does not override stack-managed variables")
        log("shadow config: OK")

    def deploy_config(self, rendered: Path) -> None:
        """Render and install the managed Hermes and sandbox configuration."""
        step("Managed configuration")
        model = self.env["HERMES_MODEL"]
        lines = self.config_source.read_text().splitlines()
        rendered.write_text("\n".join(line.replace(MODEL_REFERENCE, model) for line in lines) + "\n")
        if rendered.stat().st_size == 0:
            die("rendered config.yaml is empty")
        text = rendered.read_text()
        if MODEL_REFERENCE in text:
            die("rendered config.yaml still contains ${HERMES_MODEL}")
        deployed_model = model_default(text)
        if deployed_model != model:
            die(f"rendered model.default '{deployed_model}' does not match HERMES_MODEL='{model}'")
        uid, gid = self.env["HERMES_UID"], self.env["HERMES_GID"]
        self.run("install", "-m", "0640", "-o", uid, "-g", gid, str(rendered),
                 str(self.hermes_config / "config.yaml"))
        self.run("install", "-m", "0644", "-o", "0", "-g", "0", str(self.sandbox_dockerfile),
                 str(self.sandbox_config / "Dockerfile"))
        self.run("install", "-m", "0755", "-o", "0", "-g", "0", str(self.sandbox_entrypoint),
                 str(self.sandbox_config / "entrypoint.sh"))
        log(f"Configuration synchronized; HERMES_MODEL rendered as {model}")

    def keypair(self, private: Path, public: Path, comment: str, uid: str, gid: str) -> None:
        """Preserve a valid SSH keypair or generate one with expected permissions."""
        if private.exists() or public.exists():
            if not private.is_file() or not public.is_file() or not private.stat().st_size or not public.stat().st_size:
                die(f"incomplete SSH key pair: {private} / {public}")
            self.assert_keypair(private, public, f"inconsistent SSH key pair: {private} / {public}")
            log(f"Existing key preserved: {private}")
        else:
            os.umask(0o077)
            self.run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", str(private))
            log(f"Key created: {private}")
        self.run("chown", f"{uid}:{gid}", str(private), str(public))
        self.run("chmod", "0600", str(private))
        self.run("chmod", "0644", str(public))

    def ssh_keys(self) -> None:
        """Provision Hermes-to-sandbox authorization and sandbox host keys."""
        step("SSH keys")
        self.keypair(self.ssh_private, self.ssh_public, "hermes-sandbox",
                     self.env["HERMES_UID"], self.env["HERMES_GID"])
        self.keypair(self.host_private, self.host_public, "hermes-sandbox-host", "0", "0")
        self.run("install", "-m", "0600", "-o", self.env["SANDBOX_UID"], "-g",
                 self.env["SANDBOX_GID"], str(self.ssh_public), str(self.authorized_keys))
        log(f"Hermes -> sandbox: {self.authorized_keys}")
        log(f"Sandbox host key: {self.host_private}")

    def dependencies(self) -> None:
        """Require a running LiteLLM container on the shared network."""
        step("Existing dependencies")
        container = "litellm"
        if self.run("docker", "inspect", container, quiet=True, check=False).returncode:
            die(f"required container '{container}' does not exist")
        running = self.run("docker", "inspect", "-f", "{{.State.Running}}", container,
                           capture=True).stdout.strip()
        if running != "true":
            die(f"container '{container}' is not running")
        network = self.env["NETWORK_NAME"]
        template = '{{if index .NetworkSettings.Networks "' + network + '"}}yes{{else}}no{{end}}'
        attached = self.run("docker", "inspect", "-f", template, container, capture=True).stdout.strip()
        if attached != "yes":
            die(f"container '{container}' is not connected to {network}")
        log(f"{container}: running + {network}")

    def assert_node(self, path: Path, uid: str, gid: str, mode: int,
                    directory: bool = False, nonempty: bool = True) -> None:
        """Verify a managed file or directory's type, owner, group, and mode."""
        valid = path.is_dir() if directory else path.is_file()
        if not valid or path.is_symlink() or (not directory and nonempty and not path.stat().st_size):
            kind = ("missing or invalid directory" if directory else
                    "missing, empty, or invalid file" if nonempty else "missing or invalid file")
            die(f"{kind}: {path}")
        metadata = path.stat()
        actual = f"{metadata.st_uid}:{metadata.st_gid}:{stat.S_IMODE(metadata.st_mode):o}"
        expected = f"{uid}:{gid}:{mode:o}"
        if actual != expected:
            die(f"incorrect owner or mode for {path}: {actual}; expected {expected}")

    def assert_tree(self, root: Path, expected: list[str], recursive: bool) -> None:
        """Verify the exact expected entries under a managed directory."""
        actual = tree_entries(root, recursive)
        if actual != expected:
            kind = "tree" if recursive else "top-level entries"
            die(f"unexpected {kind} under {root}\n--- expected ---\n" + "\n".join(expected)
                + "\n--- actual ---\n" + "\n".join(actual))

    def assert_keypair(self, private: Path, public: Path, label: str) -> None:
        """Verify that a public key matches its private key."""
        derived = self.run("ssh-keygen", "-y", "-f", str(private), capture=True).stdout.split()
        actual = public.read_text().split()
        if derived[:2] != actual[:2]:
            die(label)

    def audit(self, rendered: Path) -> None:
        """Audit managed trees, permissions, content, keys, and env immutability."""
        step("Final filesystem audit")
        top = ["config", "data", "logs"]
        self.assert_tree(self.hermes_root, top, False)
        self.assert_tree(self.sandbox_root, top, False)
        self.assert_tree(self.hermes_config, ["config.yaml", "ssh", "ssh/hermes_executor_ed25519",
                                              "ssh/hermes_executor_ed25519.pub"], True)
        self.assert_tree(self.sandbox_config, ["Dockerfile", "entrypoint.sh", "ssh-host",
                                               "ssh-host/ssh_host_ed25519_key",
                                               "ssh-host/ssh_host_ed25519_key.pub"], True)
        log("Managed tree: OK")
        uid, gid = self.env["HERMES_UID"], self.env["HERMES_GID"]
        suid, sgid = self.env["SANDBOX_UID"], self.env["SANDBOX_GID"]
        for path, owner, group, mode in (
            (self.hermes_root, uid, gid, 0o750), (self.hermes_config, uid, gid, 0o750),
            (self.hermes_config / "ssh", uid, gid, 0o700), (self.hermes_data, uid, gid, 0o750),
            (self.hermes_logs, uid, gid, 0o750), (self.memory_root, uid, gid, 0o750),
            (self.memory_data, uid, gid, 0o750), (self.sandbox_root, "0", "0", 0o750),
            (self.sandbox_config, "0", "0", 0o750), (self.sandbox_config / "ssh-host", "0", "0", 0o750),
            (self.sandbox_data, "0", "0", 0o750), (self.sandbox_data / "home", suid, sgid, 0o750),
            (self.sandbox_data / "home/.ssh", suid, sgid, 0o700),
            (self.sandbox_data / "workspace", suid, sgid, 0o750),
            (self.sandbox_data / "state", "0", "0", 0o700),
            (self.sandbox_logs, suid, sgid, 0o750),
        ):
            self.assert_node(path, owner, group, mode, directory=True)
        for path, owner, group, mode, nonempty in (
            (self.memory_data / "MEMORY.md", uid, gid, 0o640, False),
            (self.memory_data / "USER.md", uid, gid, 0o640, False),
            (self.hermes_config / "config.yaml", uid, gid, 0o640, True),
            (self.ssh_private, uid, gid, 0o600, True), (self.ssh_public, uid, gid, 0o644, True),
            (self.sandbox_config / "Dockerfile", "0", "0", 0o644, True),
            (self.sandbox_config / "entrypoint.sh", "0", "0", 0o755, True),
            (self.host_private, "0", "0", 0o600, True),
            (self.host_public, "0", "0", 0o644, True),
            (self.authorized_keys, suid, sgid, 0o600, True),
        ):
            self.assert_node(path, owner, group, mode, nonempty=nonempty)
        log("Owners and permissions: OK")
        for source, deployed, message in (
            (rendered, self.hermes_config / "config.yaml", "deployed config.yaml differs from the rendered source"),
            (self.sandbox_dockerfile, self.sandbox_config / "Dockerfile", "deployed Dockerfile differs from its source"),
            (self.sandbox_entrypoint, self.sandbox_config / "entrypoint.sh", "deployed entrypoint.sh differs from its source"),
            (self.ssh_public, self.authorized_keys, "authorized_keys differs from Hermes's public key"),
        ):
            if source.read_bytes() != deployed.read_bytes():
                die(message)
        log("Managed files: OK")
        self.assert_keypair(self.ssh_private, self.ssh_public, "Hermes-to-sandbox SSH key pair is inconsistent")
        self.assert_keypair(self.host_private, self.host_public, "sandbox host key pair is inconsistent")
        log("SSH keys: OK")
        self.audit_shadow()
        deployed_text = (self.hermes_config / "config.yaml").read_text()
        if MODEL_REFERENCE in deployed_text:
            die("deployed config.yaml still contains ${HERMES_MODEL}")
        if model_default(deployed_text) != self.env["HERMES_MODEL"]:
            die(f"deployed model.default '{model_default(deployed_text)}' does not match HERMES_MODEL='{self.env['HERMES_MODEL']}'")
        log("Rendered model and shadow configuration: OK")
        if sha256(ENV_FILE) != self.env_hash:
            die(".env changed during preparation; aborting")
        log(".env unchanged: OK")

    def execute(self) -> None:
        """Prepare and audit the stack before writing its prepared-state lock."""
        self.sources()
        self.docker_preflight()
        self.persistent_filesystem()
        step("Runtime / shadow configuration")
        self.audit_shadow()
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as temporary:
            rendered = Path(temporary.name)
        try:
            self.deploy_config(rendered)
            self.ssh_keys()
            self.dependencies()
            step("Docker Compose validation")
            self.run("docker", "compose", "config", "--quiet")
            log("docker compose config: OK")
            self.audit(rendered)
        finally:
            rendered.unlink(missing_ok=True)
        step("Lock")
        # The lock represents completed preparation only after all audits pass.
        self.run("install", "-m", "0600", "-o", "0", "-g", "0", "/dev/null", str(LOCK_FILE))
        log(f"Created {LOCK_FILE}")
        print("\nStack 60 is prepared and audited; no containers were started.")
        print("Start from the repository root with: ./local-ai stack-60 start")
        print("Then check readiness with: ./local-ai stack-60 status")
        print("Git memory sync and other optional capabilities require separate setup.")
        print(".lock certifies preparation only; .env was not changed.")


def main() -> None:
    """Run preparation unless already locked, after root and tool checks."""
    if LOCK_FILE.is_file():
        print(f"LOCK: {LOCK_FILE} exists. Nothing was validated or changed.")
        return
    if os.geteuid() != 0:
        die("run this command as root")
    for command in ("docker", "ssh-keygen", "install", "grep", "chmod", "chown", "stat", "find",
                    "sort", "cmp", "sha256sum", "awk", "rm", "mktemp"):
        if shutil.which(command) is None:
            die(f"missing required command: {command}")
    if subprocess.run(["docker", "compose", "version"], capture_output=True, check=False).returncode:
        die("Docker Compose v2 is required ('docker compose')")
    if not ENV_FILE.is_file():
        die(f"missing {ENV_FILE}; this command does not create it")
    Prepare().execute()


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from None
    except (OSError, ValueError) as error:
        die(str(error))
