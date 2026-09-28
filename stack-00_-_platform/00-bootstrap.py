#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
00-bootstrap.py

Crea, de forma centralizada, el árbol de carpetas de servicio de TODOS los
stacks bajo BASE_PATH y fija su propietario y permisos. Los 01-prepare.py de
cada stack ya no crean carpetas ni ajustan sus permisos: solo verifican que
existen y copian/renderizan sus ficheros dentro.

También crea el grupo local-hybrid-pki (PLATFORM_PKI_GID), usado por HAProxy
para leer la clave privada TLS.

Uso:
  sudo ./00-bootstrap.py
  sudo ./00-bootstrap.py --dry-run     # muestra lo que haría, sin cambios

Reglas:
  - Nunca reemplaza una ruta existente: si existe debe ser un directorio real
    (no symlink); si no, falla.
  - Los directorios PGDATA de PostgreSQL solo se crean si no existen; si
    existen no se toca ni su propietario ni sus permisos (los gestiona
    PostgreSQL y cambiarlos en caliente rompe el bind mount).
  - Las carpetas marcadas como recursivas reconcilian el propietario de todo
    su contenido (como hacían antes los 01-prepare.py correspondientes).
  - En Stack2 el propietario de SearXNG/Redis/RabbitMQ es el UID/GID de la
    imagen, que se obtiene con "docker run --entrypoint id".
  - Protección de sistemas en marcha: las carpetas de un stack cuyo .lock
    existe (stack-NN_-_*/.lock, es decir, ya PREPARADO) no se modifican. Para
    reconciliarlas, borra deliberadamente ese .lock y vuelve a ejecutar.

Es idempotente: puede ejecutarse varias veces.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # nunca crear __pycache__ en el worktree

import argparse
import functools
import grp
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

STACK_DIR = Path(__file__).resolve().parent
ROOT_DIR = STACK_DIR.parent
ENV_FILE = ROOT_DIR / ".env"

PLATFORM_PKI_GROUP = "local-hybrid-pki"
SERVICE_NAME_RE = re.compile(r"^service_-_[A-Za-z0-9._-]+$")

DRY_RUN = False


@dataclass(frozen=True)
class Dir:
    """Describe la ruta, permisos y propietario deseados de un directorio."""

    path: Path
    mode: int
    uid: int | None = 0          # None: no cambiar propietario (se crea como root)
    gid: int | None = 0
    recursive: bool = False      # reconciliar propietario del contenido
    create_only: bool = False    # PGDATA: crear si falta, nunca tocar si existe


def die(message: str, code: int = 1) -> None:
    """Muestra un error y termina con el código indicado."""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def warn(message: str) -> None:
    """Muestra una advertencia sin interrumpir la ejecución."""
    print(f"WARNING: {message}", file=sys.stderr)


def log(message: str) -> None:
    """Muestra un detalle de progreso con sangría."""
    print(f"  {message}")


def step(message: str) -> None:
    """Muestra el encabezado de una fase."""
    print(f"\n== {message}")


def load_env(env_file: Path) -> dict[str, str]:
    """Carga el .env central con las mismas reglas que los scripts bash (source)."""
    if not env_file.is_file() or env_file.is_symlink():
        die(f"falta el entorno operativo raíz: {env_file}")
    result = subprocess.run(
        ["bash", "-c", 'set -a; source "$1"; set +a; env -0', "_", str(env_file)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        die(f"no se pudo cargar {env_file}: {result.stderr.decode(errors='replace').strip()}")
    env: dict[str, str] = {}
    for item in result.stdout.split(b"\0"):
        if b"=" in item:
            key, _, value = item.partition(b"=")
            env[key.decode()] = value.decode(errors="replace")
    return env


def require(env: dict[str, str], key: str) -> str:
    """Devuelve una variable no vacía o termina con un error."""
    value = env.get(key, "")
    if not value:
        die(f"falta {key} en {ENV_FILE}")
    return value


def require_int(env: dict[str, str], key: str, default: str | None = None) -> int:
    """Obtiene un entero no negativo de la variable o su valor por defecto."""
    raw = env.get(key) or default or ""
    if not raw.isdigit():
        die(f"{key} debe ser un entero no negativo (valor: {raw!r})")
    return int(raw)


def require_service_name(env: dict[str, str], key: str) -> str:
    """Valida y devuelve el nombre de servicio configurado."""
    value = require(env, key)
    if not SERVICE_NAME_RE.match(value):
        die(f"{key} debe seguir el patrón service_-_*: {value}")
    return value


def image_ref(env: dict[str, str], image_key: str, version_key: str) -> str:
    """Construye una referencia imagen:versión si ambos valores existen."""
    image, version = env.get(image_key, ""), env.get(version_key, "")
    return f"{image}:{version}" if image and version else ""


@functools.lru_cache(maxsize=None)
def image_owner(image: str) -> tuple[int, int] | None:
    """UID/GID con el que se ejecuta una imagen; None si no se puede determinar."""
    if not image or shutil.which("docker") is None:
        return None
    ids = []
    for flag in ("-u", "-g"):
        result = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "id", image, flag],
            text=True,
            capture_output=True,
            check=False,
        )
        value = result.stdout.strip()
        if result.returncode != 0 or not value.isdigit():
            return None
        ids.append(int(value))
    return ids[0], ids[1]


def ensure_group(name: str, gid: int) -> None:
    """Comprueba o crea el grupo local con el GID esperado."""
    step(f"Grupo {name}")
    try:
        existing = grp.getgrnam(name)
    except KeyError:
        existing = None
    if existing is not None:
        if existing.gr_gid != gid:
            die(f"{name} existe con GID {existing.gr_gid}, se esperaba {gid}")
        log(f"{name} ({gid}) existe")
        return
    try:
        other = grp.getgrgid(gid)
    except KeyError:
        other = None
    if other is not None:
        die(f"el GID {gid} ya lo usa el grupo {other.gr_name}; elige otro PLATFORM_PKI_GID")
    if DRY_RUN:
        log(f"[dry-run] groupadd --gid {gid} {name}")
        return
    subprocess.run(["groupadd", "--gid", str(gid), name], check=True)
    log(f"creado {name} ({gid})")


def chown_tree(root: Path, uid: int, gid: int) -> None:
    """Reconcilia el propietario del contenido de un directorio, sin seguir enlaces."""
    for current, dirs, files in os.walk(root):
        for name in dirs + files:
            os.lchown(os.path.join(current, name), uid, gid)


def ensure_dir(spec: Dir) -> None:
    """Crea o reconcilia un directorio según la especificación y el modo dry-run."""
    path = spec.path
    if path.is_symlink():
        die(f"la ruta de servicio no puede ser un symlink: {path}")
    if path.exists() and not path.is_dir():
        die(f"la ruta de servicio existe y no es un directorio: {path}")

    owner = "sin cambios" if spec.uid is None else f"{spec.uid}:{spec.gid}"
    description = f"{path} {spec.mode:04o} {owner}{' (recursivo)' if spec.recursive else ''}"

    if spec.create_only and path.is_dir():
        log(f"{path}: existente, preservado (PGDATA)")
        return

    if DRY_RUN:
        log(f"[dry-run] {description}")
        return

    if not path.exists():
        path.mkdir(mode=0o700, parents=True)
        os.chown(path, 0, 0)
    if spec.uid is not None and spec.gid is not None:
        os.chown(path, spec.uid, spec.gid)
        if spec.recursive:
            chown_tree(path, spec.uid, spec.gid)
    os.chmod(path, spec.mode)
    log(description)


def build_layout(env: dict[str, str]) -> list[tuple[str, Callable[[], list[Dir]]]]:
    """Devuelve (stack, constructor). Cada constructor solo se evalúa si el
    stack no está PREPARADO (.lock), así un stack bloqueado ni siquiera lanza
    docker run ni valida sus variables."""
    base = Path(env["BASE_PATH"].rstrip("/"))

    def svc(name: str) -> Path:
        """Devuelve la ruta de servicio bajo BASE_PATH."""
        return base / name

    def stack0() -> list[Dir]:
        """Define los directorios de estado y registros de la plataforma."""
        platform = svc("service_-_platform")
        return [
            Dir(base, 0o750),
            Dir(platform, 0o750),
            Dir(platform / "state", 0o700),
            Dir(platform / "logs", 0o750),
        ]

    def stack1() -> list[Dir]:
        """Define los directorios de HAProxy y la web con acceso PKI."""
        # HAProxy (uid 99) lee config/ (haproxy.cfg + tls.crt + tls.key) gracias
        # al grupo suplementario PLATFORM_PKI_GID.
        pki_gid = require_int(env, "PLATFORM_PKI_GID", "1999")
        haproxy = svc("service_-_haproxy")
        return [
            Dir(haproxy, 0o750, 0, pki_gid),
            Dir(haproxy / "config", 0o750, 0, pki_gid),
            Dir(svc("service_-_web"), 0o755),
        ]

    def stack2() -> list[Dir]:
        """Define los datos persistentes de SearXNG y Firecrawl."""
        def image_dir(path: Path, image: str, label: str) -> Dir:
            """Usa el UID/GID de la imagen o conserva el propietario si se desconoce."""
            owner = image_owner(image)
            if owner is None:
                warn(f"{label}: no se pudo determinar UID/GID de la imagen '{image}'; se conserva el propietario")
                return Dir(path, 0o755, None, None)
            uid, gid = owner
            if uid == 0:
                return Dir(path, 0o755)
            return Dir(path, 0o755, uid, gid, recursive=True)

        searxng = svc("service_-_searxng")
        redis = svc("service_-_firecrawl-redis")
        rabbitmq = svc("service_-_firecrawl-rabbitmq")
        fc_postgres = svc("service_-_firecrawl-postgres")
        searxng_image = env.get("SEARXNG_IMAGE", "")
        redis_image = image_ref(env, "FIRECRAWL_REDIS_IMAGE", "FIRECRAWL_REDIS_VERSION")
        rabbitmq_image = image_ref(env, "FIRECRAWL_RABBITMQ_IMAGE", "FIRECRAWL_RABBITMQ_VERSION")
        return [
            Dir(searxng, 0o750),
            image_dir(searxng / "config", searxng_image, "searxng"),
            image_dir(searxng / "data", searxng_image, "searxng"),
            Dir(redis, 0o750),
            image_dir(redis / "data", redis_image, "firecrawl-redis"),
            Dir(rabbitmq, 0o750),
            image_dir(rabbitmq / "data", rabbitmq_image, "firecrawl-rabbitmq"),
            Dir(fc_postgres, 0o750),
            Dir(fc_postgres / "data", 0o700, create_only=True),
            Dir(fc_postgres / "secret", 0o700),
        ]

    def stack3() -> list[Dir]:
        """Define configuración de LiteLLM y datos y secretos de PostgreSQL."""
        litellm = svc("service_-_litellm")
        litellm_postgres = svc("service_-_litellm-postgres")
        return [
            Dir(litellm, 0o750),
            Dir(litellm / "config", 0o750),
            Dir(litellm_postgres, 0o750),
            Dir(litellm_postgres / "data", 0o700, create_only=True),
            Dir(litellm_postgres / "secret", 0o700),
        ]

    def stack4() -> list[Dir]:
        """Define los directorios de Gitea y su runner."""
        gitea_uid = require_int(env, "GITEA_UID")
        gitea_gid = require_int(env, "GITEA_GID")
        gitea = svc("service_-_gitea")
        runner = svc("service_-_gitea-runner")
        return [
            Dir(gitea, 0o750),
            Dir(gitea / "config", 0o750, gitea_uid, gitea_gid, recursive=True),
            Dir(gitea / "config" / "conf", 0o750, gitea_uid, gitea_gid),
            Dir(gitea / "data", 0o750, gitea_uid, gitea_gid, recursive=True),
            Dir(runner, 0o750),
            Dir(runner / "data", 0o750, gitea_uid, gitea_gid, recursive=True),
            Dir(runner / "secret", 0o750, 0, gitea_gid),
        ]

    # Stack5: Dockhand usa un volumen Docker externo (dockhand_data), no
    # carpetas en BASE_PATH; lo gestiona su propio 01-prepare.py.

    def stack6() -> list[Dir]:
        """Define los directorios de Hermes, memoria y sandbox."""
        hermes_owner = (require_int(env, "HERMES_UID"), require_int(env, "HERMES_GID"))
        sandbox_owner = (require_int(env, "SANDBOX_UID"), require_int(env, "SANDBOX_GID"))
        names = {
            key: require_service_name(env, key)
            for key in ("HERMES_SERVICE", "HERMES_MEMORY_SERVICE", "MEMORY_SYNC_SERVICE", "SANDBOX_SERVICE")
        }
        if len(set(names.values())) != len(names):
            die("HERMES_SERVICE, HERMES_MEMORY_SERVICE, MEMORY_SYNC_SERVICE y SANDBOX_SERVICE deben ser distintos")
        hermes = svc(names["HERMES_SERVICE"])
        memory = svc(names["HERMES_MEMORY_SERVICE"])
        memory_sync = svc(names["MEMORY_SYNC_SERVICE"])
        sandbox = svc(names["SANDBOX_SERVICE"])
        return [
            Dir(hermes, 0o750, *hermes_owner),
            Dir(hermes / "config", 0o750, *hermes_owner),
            Dir(hermes / "config" / "ssh", 0o700, *hermes_owner),
            Dir(hermes / "data", 0o750, *hermes_owner),
            Dir(hermes / "logs", 0o750, *hermes_owner),
            Dir(memory, 0o750, *hermes_owner),
            Dir(memory / "data", 0o750, *hermes_owner),
            Dir(memory_sync, 0o750, *hermes_owner),
            Dir(memory_sync / "ssh", 0o700, *hermes_owner),
            Dir(sandbox, 0o750),
            Dir(sandbox / "config", 0o750),
            Dir(sandbox / "config" / "ssh-host", 0o750),
            Dir(sandbox / "data", 0o750),
            Dir(sandbox / "data" / "home", 0o750, *sandbox_owner),
            Dir(sandbox / "data" / "home" / ".ssh", 0o700, *sandbox_owner),
            Dir(sandbox / "data" / "workspace", 0o750, *sandbox_owner),
            Dir(sandbox / "data" / "state", 0o700),
            Dir(sandbox / "logs", 0o750, *sandbox_owner),
        ]

    def stack7() -> list[Dir]:
        """Define el directorio de datos de Open WebUI."""
        openwebui = svc("service_-_open-webui")
        return [
            Dir(openwebui, 0o750),
            Dir(openwebui / "data", 0o750),
        ]

    return [
        ("stack-00_-_platform", stack0),
        ("stack-10_-_haproxy_web", stack1),
        ("stack-20_-_searxng_firecrawl", stack2),
        ("stack-30_-_litellm", stack3),
        ("stack-40_-_gitea", stack4),
        ("stack-60_-_hermes", stack6),
        ("stack-70_-_open-webui", stack7),
    ]


def parse_args() -> argparse.Namespace:
    """Lee la opción --dry-run de la línea de comandos."""
    parser = argparse.ArgumentParser(
        description="Crea el árbol de carpetas de servicio de todos los stacks y fija sus permisos.",
    )
    parser.add_argument("--dry-run", action="store_true", help="muestra las acciones sin aplicarlas")
    return parser.parse_args()


def main() -> None:
    """Valida el entorno y reconcilia solo los stacks sin .lock."""
    global DRY_RUN
    sys.stdout.reconfigure(line_buffering=True)
    args = parse_args()
    DRY_RUN = args.dry_run

    if os.geteuid() != 0 and not DRY_RUN:
        die("ejecuta el script con sudo/root")
    if shutil.which("groupadd") is None and not DRY_RUN:
        die("falta el comando requerido: groupadd")

    env = load_env(ENV_FILE)
    stacks_root = require(env, "STACKS_ROOT").rstrip("/")
    base_path = require(env, "BASE_PATH").rstrip("/")
    if not stacks_root.startswith("/") or not base_path.startswith("/"):
        die("STACKS_ROOT y BASE_PATH deben ser rutas absolutas")
    if not base_path or base_path == "/":
        die("BASE_PATH no puede ser /")
    if str(ROOT_DIR) != stacks_root:
        die(f"el worktree debe estar en {stacks_root}; ruta actual: {ROOT_DIR}")
    if stacks_root == base_path:
        die("STACKS_ROOT y BASE_PATH deben ser distintos")

    pki_gid = require_int(env, "PLATFORM_PKI_GID", "1999")
    if pki_gid <= 0:
        die("PLATFORM_PKI_GID debe ser un entero positivo")

    ensure_group(PLATFORM_PKI_GROUP, pki_gid)

    skipped: list[str] = []
    for stack, build in build_layout(env):
        step(f"Carpetas de {stack}")
        lock = ROOT_DIR / stack / ".lock"
        if lock.exists():
            log(f"PREPARADO ({lock}): carpetas y permisos no se modifican")
            skipped.append(stack)
            continue
        for spec in build():
            ensure_dir(spec)

    step("Estructura base completa" if not DRY_RUN else "Dry-run completo; no se ha modificado nada")
    log(f"BASE_PATH: {base_path}")
    if skipped:
        log("stacks preparados omitidos (borra su .lock para reconciliarlos): " + ", ".join(skipped))


if __name__ == "__main__":
    main()
