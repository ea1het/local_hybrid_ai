#!/usr/bin/env python3
"""Prepare and audit the Hermes runtime without starting containers."""

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

from stack_env import load_env


STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"
LOCK_FILE = STACK_DIR / ".lock"
ALL_KEYS = """STACKS_ROOT BASE_PATH NETWORK_NAME TZ HERMES_SERVICE HERMES_MEMORY_SERVICE MEMORY_SYNC_SERVICE SANDBOX_SERVICE
HERMES_CONTAINER MEMORY_SYNC_CONTAINER SANDBOX_CONTAINER SANDBOX_CLEANUP_CONTAINER
HERMES_IMAGE HERMES_VERSION SANDBOX_IMAGE MEMORY_SYNC_IMAGE SANDBOX_CLEANUP_IMAGE HERMES_UID HERMES_GID
HERMES_MODEL LITELLM_BASE_URL LITELLM_API_KEY LITELLM_MCP_URL LITELLM_MCP_API_KEY TELEGRAM_BOT_TOKEN
HERMES_DASHBOARD HERMES_DASHBOARD_HOST API_SERVER_ENABLED API_SERVER_HOST API_SERVER_PORT API_SERVER_KEY
API_SERVER_MODEL_NAME API_SERVER_CORS_ORIGINS SEARXNG_URL FIRECRAWL_API_URL FIRECRAWL_API_KEY
TERMINAL_SSH_HOST TERMINAL_SSH_USER TERMINAL_SSH_PORT TERMINAL_SSH_KEY TERMINAL_SSH_PERSISTENT TERMINAL_TIMEOUT
SANDBOX_UID SANDBOX_GID SANDBOX_CPU SANDBOX_MEMORY SANDBOX_PIDS SANDBOX_SHM_SIZE
MEMORY_SYNC_INTERVAL_SECONDS GITMEM_REPOSITORY GITMEM_BRANCH SANDBOX_CLEANUP_RETENTION_DAYS
SANDBOX_CLEANUP_QUARANTINE_DAYS SANDBOX_CLEANUP_DB_RETENTION_DAYS SANDBOX_CLEANUP_SWEEP_HOUR
SANDBOX_CLEANUP_SWEEP_MINUTE""".split()
OPTIONAL_EMPTY = {"TELEGRAM_BOT_TOKEN", "API_SERVER_CORS_ORIGINS", "SEARXNG_URL", "FIRECRAWL_API_URL",
                  "FIRECRAWL_API_KEY", "GITMEM_REPOSITORY", "GITMEM_BRANCH"}
RUNTIME_ALLOWED = {
    "BROWSERBASE_ADVANCED_STEALTH", "BROWSERBASE_PROXIES", "BROWSER_INACTIVITY_TIMEOUT",
    "BROWSER_SESSION_TIMEOUT", "IMAGE_TOOLS_DEBUG", "MOA_TOOLS_DEBUG", "TERMINAL_LIFETIME_SECONDS",
    "TERMINAL_MODAL_IMAGE", "TERMINAL_TIMEOUT", "VISION_TOOLS_DEBUG", "WEB_TOOLS_DEBUG",
}
RUNTIME_KEY = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")
MODEL_REFERENCE = "${HERMES_MODEL}"


def log(message: str) -> None:
    print(f"  {message}")


def step(message: str) -> None:
    print(f"\n== {message}")


def warn(message: str) -> None:
    print(f"  AVISO: {message}", file=sys.stderr)


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def model_default(text: str) -> str:
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
    if not recursive:
        return sorted(child.name for child in root.iterdir())
    return sorted(str(child.relative_to(root)) for child in root.rglob("*"))


class Prepare:
    def __init__(self):
        self.env_hash = sha256(ENV_FILE)
        step("Validacion de .env (solo lectura)")
        lines = ENV_FILE.read_text().splitlines()
        for key in ALL_KEYS:
            if not any(line.startswith(f"{key}=") for line in lines):
                die(f"falta la variable {key} en .env")
        self.env = load_env(ENV_FILE)
        for key in ALL_KEYS:
            if key in OPTIONAL_EMPTY:
                continue
            value = self.env.get(key, "")
            if not value:
                die(f"{key} esta vacia en .env")
            if value.startswith("CHANGE_ME"):
                die(f"{key} sigue sin definir: {value}")
            if value.startswith("PUT_YOUR_"):
                die(f"{key} sigue usando un placeholder: {value}")
        env = self.env
        if len(env["API_SERVER_KEY"]) < 8:
            die("API_SERVER_KEY debe tener al menos 8 caracteres")
        if len(env["LITELLM_MCP_API_KEY"]) < 8:
            die("LITELLM_MCP_API_KEY debe tener al menos 8 caracteres")
        if env["HERMES_VERSION"] == "latest":
            die("HERMES_VERSION no puede ser latest")
        if env["HERMES_IMAGE"].endswith(":latest"):
            die("HERMES_IMAGE no puede incluir :latest")
        if not re.fullmatch(r"https?://\S+/mcp/?", env["LITELLM_MCP_URL"]):
            die("LITELLM_MCP_URL debe ser un endpoint HTTP(S) terminado en /mcp")
        token = env.get("TELEGRAM_BOT_TOKEN", "")
        if token:
            if token.startswith("CHANGE_ME"):
                die("TELEGRAM_BOT_TOKEN sigue sin definir")
            if token.startswith("PUT_YOUR_"):
                die("TELEGRAM_BOT_TOKEN sigue usando un placeholder")
            if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]{30,}", token):
                die("TELEGRAM_BOT_TOKEN no tiene el formato esperado de BotFather")
        for key in ("STACKS_ROOT", "BASE_PATH"):
            if not env[key].startswith("/"):
                die(f"{key} debe ser una ruta absoluta")
            env[key] = env[key][:-1] if env[key].endswith("/") else env[key]
            if not env[key]:
                die(f"{key} no puede ser /")
        if str(STACK_DIR) != f"{env['STACKS_ROOT']}/stack-60_-_hermes":
            die(f"Stack6 debe residir en {env['STACKS_ROOT']}/stack-60_-_hermes; ruta actual: {STACK_DIR}")
        for number, name in ((0, "platform"), (3, "litellm")):
            lock = Path(env["STACKS_ROOT"]) / f"stack-{number * 10:02d}_-_{name}" / ".lock"
            if not lock.is_file():
                die(f"Stack{number} no esta preparado: falta {lock}")
        for key in ("HERMES_SERVICE", "HERMES_MEMORY_SERVICE", "MEMORY_SYNC_SERVICE", "SANDBOX_SERVICE"):
            if not re.fullmatch(r"service_-_[A-Za-z0-9._-]+", env[key]):
                die(f"{key} debe seguir el patron service_-_*")
        for first, second in (("HERMES_SERVICE", "SANDBOX_SERVICE"),
                              ("HERMES_SERVICE", "HERMES_MEMORY_SERVICE"),
                              ("SANDBOX_SERVICE", "HERMES_MEMORY_SERVICE")):
            if env[first] == env[second]:
                die(f"{first} y {second} no pueden ser iguales")
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
        log(".env completo; no se ha modificado")
        log(f"Hermes fijado a {env['HERMES_IMAGE']}:{env['HERMES_VERSION']}")
        log(f"memoria externa declarada: {self.memory_data}")
        log(f"MCP gateway: {env['LITELLM_MCP_URL']}")
        log("Telegram: habilitado; token presente y formato valido" if token else
            "Telegram: deshabilitado; TELEGRAM_BOT_TOKEN vacio")

    def run(self, *args: str, capture: bool = False, quiet: bool = False,
            check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, cwd=STACK_DIR, env=self.env, text=True, check=check,
                              stdout=subprocess.PIPE if capture else subprocess.DEVNULL if quiet else None,
                              stderr=subprocess.DEVNULL if quiet else None)

    def sources(self) -> None:
        step("Ficheros fuente del stack")
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
                die(f"falta o esta vacio {source}")
        text = self.config_source.read_text()
        for key in ("HERMES_MODEL", "LITELLM_MCP_URL", "LITELLM_MCP_API_KEY"):
            if "${" + key + "}" not in text:
                die(f"config/hermes/config.yaml debe contener ${{{key}}}")
        model = self.env["HERMES_MODEL"]
        if not re.fullmatch(r"[A-Za-z0-9._:/+@-]+", model):
            die(f"HERMES_MODEL contiene caracteres no admitidos para render seguro: {model}")
        if model_default(text) != MODEL_REFERENCE:
            die("model.default en config/hermes/config.yaml debe ser ${HERMES_MODEL}")
        for line in text.splitlines():
            match = re.match(r"\s+model:\s+(.+)", line)
            if match and match.group(1) != MODEL_REFERENCE:
                die(f"referencia de modelo hardcodeada en config/hermes/config.yaml: {match.group(1)}")
        summary = next((match.group(1) for line in text.splitlines()
                        if (match := re.match(r"\s*summary_model:\s*(.*)", line))), "")
        if summary and summary != MODEL_REFERENCE:
            die("compression.summary_model debe ser ${HERMES_MODEL}")
        if re.search(r"(^|\s)(install|chown|chmod)(\s|$)|hermes_authorized_key|AUTHORIZED_SOURCE",
                     self.sandbox_entrypoint.read_text(), re.MULTILINE):
            die("entrypoint.sh contiene logica de preparacion antigua; no se instala")
        log("fuentes presentes y coherentes")

    def docker_preflight(self) -> None:
        name = self.env["NETWORK_NAME"]
        step(f"Red Docker {name}")
        if self.run("docker", "network", "inspect", name, quiet=True, check=False).returncode:
            die(f"falta la red compartida {name}; debe crearla Stack0")
        driver = self.run("docker", "network", "inspect", "-f", "{{.Driver}}", name, capture=True).stdout.strip()
        if driver != "bridge":
            die(f"la red {name} existe pero usa driver '{driver}', no bridge")
        log("existe, es bridge y permanece propiedad de Stack0")
        step("Estado de Hermes")
        for container in (self.env["HERMES_CONTAINER"], self.env["SANDBOX_CONTAINER"]):
            if self.run("docker", "inspect", container, quiet=True, check=False).returncode == 0:
                running = self.run("docker", "inspect", "-f", "{{.State.Running}}", container,
                                   capture=True).stdout.strip()
                if running == "true":
                    die(f"el contenedor '{container}' sigue corriendo; ejecutar docker compose stop")
                log(f"{container}: detenido")
            else:
                log(f"{container}: no creado")

    def persistent_filesystem(self) -> None:
        step("Creacion/verificacion del arbol objetivo")
        paths = (self.hermes_root, self.hermes_config, self.hermes_config / "ssh", self.hermes_data,
                 self.hermes_logs, self.memory_root, self.memory_data, self.sandbox_root,
                 self.sandbox_config, self.sandbox_config / "ssh-host", self.sandbox_data,
                 self.sandbox_data / "home", self.sandbox_data / "home/.ssh",
                 self.sandbox_data / "workspace", self.sandbox_data / "state", self.sandbox_logs)
        for path in paths:
            if not path.is_dir() or path.is_symlink():
                die(f"falta {path}; ejecuta primero stack-00_-_platform/00-bootstrap.py")
        uid, gid = self.env["HERMES_UID"], self.env["HERMES_GID"]
        for name in ("MEMORY.md", "USER.md"):
            path = self.memory_data / name
            if path.exists():
                if not path.is_file() or path.is_symlink():
                    die(f"{path} debe ser un fichero regular")
                log(f"memoria existente preservada: {name}")
            else:
                self.run("install", "-m", "0640", "-o", uid, "-g", gid, "/dev/null", str(path))
                log(f"memoria local inicial creada: {name}")
            self.run("chown", f"{uid}:{gid}", str(path))
            self.run("chmod", "0640", str(path))
        log(f"{self.hermes_root}/{{config,data,logs}}")
        log(f"{self.memory_data}: memoria persistente local")
        log(f"{self.sandbox_root}/{{config,data,logs}}")
        log("data/, logs/, workspace, memoria y data/bin se preservan")
        log("Git memory-sync es opcional y no forma parte del Stack6 minimo")

    def audit_shadow(self) -> None:
        runtime_env = self.hermes_data / ".env"
        runtime_config = self.hermes_data / "config.yaml"
        shadow = self.hermes_data / ".hermes"
        if present(shadow):
            die(f"configuracion shadow detectada: {shadow}; ejecutar cleanup.py")
        if runtime_config.is_symlink():
            die(f"configuracion shadow detectada (symlink): {runtime_config}; ejecutar cleanup.py")
        if runtime_config.exists():
            if not runtime_config.is_file():
                die(f"configuracion shadow invalida: {runtime_config}; ejecutar cleanup.py")
            if runtime_config.stat().st_size:
                die(f"configuracion shadow activa y no vacia: {runtime_config}; ejecutar cleanup.py")
            warn("data/config.yaml vacio permitido; queda oculto por el bind mount gestionado")
        if runtime_env.is_symlink():
            die(f"runtime .env no puede ser un symlink: {runtime_env}")
        if runtime_env.exists():
            if not runtime_env.is_file():
                die(f"runtime .env no es un fichero regular: {runtime_env}")
            managed = ENV_FILE.read_text().splitlines()
            for line in runtime_env.read_text().splitlines():
                match = RUNTIME_KEY.match(line)
                if match and match.group(1) not in RUNTIME_ALLOWED:
                    key = match.group(1)
                    if any(entry.startswith(f"{key}=") for entry in managed):
                        die(f"runtime .env intenta redefinir variable gestionada por el stack: {key}")
            log("data/.env runtime permitido; sin colisiones con variables gestionadas por el stack")
        log("shadow config: OK")

    def deploy_config(self, rendered: Path) -> None:
        step("Configuracion gestionada")
        model = self.env["HERMES_MODEL"]
        lines = self.config_source.read_text().splitlines()
        rendered.write_text("\n".join(line.replace(MODEL_REFERENCE, model) for line in lines) + "\n")
        if rendered.stat().st_size == 0:
            die("config.yaml renderizado esta vacio")
        text = rendered.read_text()
        if MODEL_REFERENCE in text:
            die("config.yaml renderizado conserva ${HERMES_MODEL}; se aborta")
        deployed_model = model_default(text)
        if deployed_model != model:
            die(f"model.default renderizado '{deployed_model}' no coincide con HERMES_MODEL='{model}'")
        uid, gid = self.env["HERMES_UID"], self.env["HERMES_GID"]
        self.run("install", "-m", "0640", "-o", uid, "-g", gid, str(rendered),
                 str(self.hermes_config / "config.yaml"))
        self.run("install", "-m", "0644", "-o", "0", "-g", "0", str(self.sandbox_dockerfile),
                 str(self.sandbox_config / "Dockerfile"))
        self.run("install", "-m", "0755", "-o", "0", "-g", "0", str(self.sandbox_entrypoint),
                 str(self.sandbox_config / "entrypoint.sh"))
        log(f"configuracion sincronizada; HERMES_MODEL renderizado como {model}")

    def keypair(self, private: Path, public: Path, comment: str, uid: str, gid: str) -> None:
        if private.exists() or public.exists():
            if not private.is_file() or not public.is_file() or not private.stat().st_size or not public.stat().st_size:
                die(f"pareja SSH incompleta: {private} / {public}")
            self.assert_keypair(private, public, f"pareja SSH incoherente: {private} / {public}")
            log(f"clave existente conservada: {private}")
        else:
            os.umask(0o077)
            self.run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", str(private))
            log(f"clave creada: {private}")
        self.run("chown", f"{uid}:{gid}", str(private), str(public))
        self.run("chmod", "0600", str(private))
        self.run("chmod", "0644", str(public))

    def ssh_keys(self) -> None:
        step("Claves SSH")
        self.keypair(self.ssh_private, self.ssh_public, "hermes-sandbox",
                     self.env["HERMES_UID"], self.env["HERMES_GID"])
        self.keypair(self.host_private, self.host_public, "hermes-sandbox-host", "0", "0")
        self.run("install", "-m", "0600", "-o", self.env["SANDBOX_UID"], "-g",
                 self.env["SANDBOX_GID"], str(self.ssh_public), str(self.authorized_keys))
        log(f"Hermes -> sandbox: {self.authorized_keys}")
        log(f"host key sandbox: {self.host_private}")

    def dependencies(self) -> None:
        step("Dependencias existentes")
        container = "litellm"
        if self.run("docker", "inspect", container, quiet=True, check=False).returncode:
            die(f"no existe el contenedor requerido '{container}'")
        running = self.run("docker", "inspect", "-f", "{{.State.Running}}", container,
                           capture=True).stdout.strip()
        if running != "true":
            die(f"el contenedor '{container}' no esta corriendo")
        network = self.env["NETWORK_NAME"]
        template = '{{if index .NetworkSettings.Networks "' + network + '"}}yes{{else}}no{{end}}'
        attached = self.run("docker", "inspect", "-f", template, container, capture=True).stdout.strip()
        if attached != "yes":
            die(f"el contenedor '{container}' no esta conectado a {network}")
        log(f"{container}: running + {network}")

    def assert_node(self, path: Path, uid: str, gid: str, mode: int,
                    directory: bool = False, nonempty: bool = True) -> None:
        valid = path.is_dir() if directory else path.is_file()
        if not valid or path.is_symlink() or (not directory and nonempty and not path.stat().st_size):
            kind = ("directorio ausente o invalido" if directory else
                    "fichero ausente, vacio o invalido" if nonempty else "fichero ausente o invalido")
            die(f"{kind}: {path}")
        metadata = path.stat()
        actual = f"{metadata.st_uid}:{metadata.st_gid}:{stat.S_IMODE(metadata.st_mode):o}"
        expected = f"{uid}:{gid}:{mode:o}"
        if actual != expected:
            die(f"permisos/propietario incorrectos en {path}: {actual} esperado {expected}")

    def assert_tree(self, root: Path, expected: list[str], recursive: bool) -> None:
        actual = tree_entries(root, recursive)
        if actual != expected:
            kind = "arbol" if recursive else "top-level"
            die(f"{kind} inesperado bajo {root}\n--- esperado ---\n" + "\n".join(expected)
                + "\n--- real ---\n" + "\n".join(actual))

    def assert_keypair(self, private: Path, public: Path, label: str) -> None:
        derived = self.run("ssh-keygen", "-y", "-f", str(private), capture=True).stdout.split()
        actual = public.read_text().split()
        if derived[:2] != actual[:2]:
            die(label)

    def audit(self, rendered: Path) -> None:
        step("Auditoria final del filesystem")
        top = ["config", "data", "logs"]
        self.assert_tree(self.hermes_root, top, False)
        self.assert_tree(self.sandbox_root, top, False)
        self.assert_tree(self.hermes_config, ["config.yaml", "ssh", "ssh/hermes_executor_ed25519",
                                              "ssh/hermes_executor_ed25519.pub"], True)
        self.assert_tree(self.sandbox_config, ["Dockerfile", "entrypoint.sh", "ssh-host",
                                               "ssh-host/ssh_host_ed25519_key",
                                               "ssh-host/ssh_host_ed25519_key.pub"], True)
        log("arbol gestionado: OK")
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
        log("propietarios/permisos: OK")
        for source, deployed, message in (
            (rendered, self.hermes_config / "config.yaml", "config.yaml desplegado no coincide con el render esperado"),
            (self.sandbox_dockerfile, self.sandbox_config / "Dockerfile", "Dockerfile desplegado no coincide con la fuente"),
            (self.sandbox_entrypoint, self.sandbox_config / "entrypoint.sh", "entrypoint.sh desplegado no coincide con la fuente"),
            (self.ssh_public, self.authorized_keys, "authorized_keys no coincide con la clave publica de Hermes"),
        ):
            if source.read_bytes() != deployed.read_bytes():
                die(message)
        log("ficheros gestionados: OK")
        self.assert_keypair(self.ssh_private, self.ssh_public, "la pareja SSH Hermes -> sandbox no es coherente")
        self.assert_keypair(self.host_private, self.host_public, "la pareja de host keys del sandbox no es coherente")
        log("claves SSH: OK")
        self.audit_shadow()
        deployed_text = (self.hermes_config / "config.yaml").read_text()
        if MODEL_REFERENCE in deployed_text:
            die("config.yaml desplegado contiene ${HERMES_MODEL}")
        if model_default(deployed_text) != self.env["HERMES_MODEL"]:
            die(f"model.default desplegado '{model_default(deployed_text)}' no coincide con HERMES_MODEL='{self.env['HERMES_MODEL']}'")
        log("modelo renderizado / shadow config: OK")
        if sha256(ENV_FILE) != self.env_hash:
            die(".env ha cambiado durante la preparacion; se aborta")
        log(".env inmutable: OK")

    def execute(self) -> None:
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
            step("Validacion Docker Compose")
            self.run("docker", "compose", "config", "--quiet")
            log("docker compose config: OK")
            self.audit(rendered)
        finally:
            rendered.unlink(missing_ok=True)
        step("Lock")
        self.run("install", "-m", "0600", "-o", "0", "-g", "0", "/dev/null", str(LOCK_FILE))
        log(f"creado {LOCK_FILE}")
        print(f"""
Stack preparado y auditado. No se ha arrancado ningun contenedor.

Siguiente paso:

  cd {STACK_DIR}
  docker compose up -d --build
  python3 ./reconcile-capabilities.py --restart
  docker compose ps

Git-backed memory es opcional. Para habilitarla posteriormente:

  python3 ./prepare-git-memory.py
  python3 ./prepare-maintenance-sidecars.py
  docker compose --profile git-memory up -d --build hermes-memory-sync

La salida correcta del prepare incluye:

  arbol gestionado: OK
  propietarios/permisos: OK
  ficheros gestionados: OK
  claves SSH: OK
  modelo renderizado / shadow config: OK
  .env inmutable: OK

IMPORTANTE:
  - .lock significa PREPARED; no significa desplegado ni healthy.
  - 01-prepare.py crea o conserva la memoria persistente local de Stack6.
  - prepare-git-memory.py habilita/valida opcionalmente el working tree Git de memoria.
  - reconcile-capabilities.py adapta la configuracion a providers opcionales.
  - 01-prepare.py no borra data/, logs/, workspace, memoria, state.db ni data/bin.
  - la limpieza/reset/factory-reset corresponde a cleanup.py.
  - .env no se modifica nunca.""")


def main() -> None:
    if LOCK_FILE.is_file():
        print(f"LOCK: {LOCK_FILE} existe. No se valida ni se modifica nada.")
        return
    if os.geteuid() != 0:
        die("ejecutar como root")
    for command in ("docker", "ssh-keygen", "install", "grep", "chmod", "chown", "stat", "find",
                    "sort", "cmp", "sha256sum", "awk", "rm", "mktemp"):
        if shutil.which(command) is None:
            die(f"falta el comando requerido: {command}")
    if subprocess.run(["docker", "compose", "version"], capture_output=True, check=False).returncode:
        die("se requiere Docker Compose v2 ('docker compose')")
    if not ENV_FILE.is_file():
        die(f"falta {ENV_FILE}; el script no lo crea")
    Prepare().execute()


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from None
    except (OSError, ValueError) as error:
        die(str(error))
