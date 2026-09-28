#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Adopt an existing Git repository as persistent Hermes memory."""

import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
import tempfile
from pathlib import Path, PurePosixPath

from stack_env import load_env


STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"
LOCK_FILE = STACK_DIR / ".lock"
MEMORY_FILES = ("MEMORY.md", "USER.md")


def log(message: str) -> None:
    """Print an indented progress message."""
    print(f"  {message}")


def step(message: str) -> None:
    """Print a section heading."""
    print(f"\n== {message}")


def fail(message: str) -> None:
    """Report a Git memory preparation error and exit."""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(*args: str, capture: bool = False, quiet: bool = False) -> subprocess.CompletedProcess[bytes]:
    """Run a command, with optional stdout capture or output suppression."""
    return subprocess.run(args, check=True, stdout=subprocess.PIPE if capture else subprocess.DEVNULL if quiet else None,
                          stderr=subprocess.DEVNULL if quiet else None)


def git(tree: Path, *args: str, capture: bool = False, quiet: bool = False) -> subprocess.CompletedProcess[bytes]:
    """Run Git against a tree while explicitly marking it as safe."""
    return run("git", "-c", f"safe.directory={tree}", "-C", str(tree), *args, capture=capture, quiet=quiet)


def git_text(tree: Path, *args: str) -> str:
    """Return trimmed text output from a Git command."""
    return git(tree, *args, capture=True).stdout.decode().strip()


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular(path: Path) -> bool:
    """Check that a path is a nonsymlink regular file."""
    return path.is_file() and not path.is_symlink()


def same_content(first: Path, second: Path) -> bool:
    """Compare the bytes of two files."""
    return first.read_bytes() == second.read_bytes()


def tracked_paths(tree: Path) -> list[str]:
    """List tracked paths using NUL-delimited Git output."""
    entries = git(tree, "ls-files", "-z", capture=True).stdout.split(b"\0")
    return sorted(os.fsdecode(entry) for entry in entries if entry)


def validate_static_path(tree: Path, relative: str) -> Path:
    """Reject unsafe or nonregular tracked paths before copying static content."""
    parts = PurePosixPath(relative).parts
    if not parts or any(part in (".", "..", ".git") for part in parts) or PurePosixPath(relative).is_absolute():
        fail(f"fichero estatico versionado no admitido: {relative} debe ser fichero normal")
    current = tree
    for part in parts[:-1]:
        current /= part
        if not current.is_dir() or current.is_symlink():
            fail(f"fichero estatico versionado no admitido: {relative} debe ser fichero normal")
    target = current / parts[-1]
    if not regular(target):
        fail(f"fichero estatico versionado no admitido: {relative} debe ser fichero normal")
    return target


def validate_identity(tree: Path, repository: str, expected_branch: str) -> tuple[str, str]:
    """Verify remote, branch, and both tracked memory files."""
    origin = git_text(tree, "remote", "get-url", "origin")
    if not origin:
        fail("el working tree no tiene remote origin")
    if origin != repository:
        fail(f"origin inesperado: '{origin}' (esperado '{repository}')")
    branch = git_text(tree, "branch", "--show-current")
    if branch != expected_branch:
        fail(f"branch activa inesperada: '{branch}' (esperada '{expected_branch}')")
    for name in MEMORY_FILES:
        if subprocess.run(["git", "-c", f"safe.directory={tree}", "-C", str(tree),
                           "ls-files", "--error-unmatch", "--", name],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            fail(f"Git memory debe versionar {name}")
        if not regular(tree / name):
            fail(f"el repositorio debe contener {name} como fichero normal")
    return origin, branch


def adopt(memory_root: Path, data: Path, legacy: Path, repository: str, branch: str, uid: int, gid: int) -> None:
    """Adopt validated Git metadata while preserving the persistent memory directory."""
    if (data / ".git").is_dir() and not (data / ".git").is_symlink():
        log("working tree existente conservado")
        return
    if (data / ".git").exists() or (data / ".git").is_symlink():
        fail(f"{data}/.git existe pero no es un directorio normal")
    unexpected = sorted(entry.name for entry in data.iterdir() if entry.name not in MEMORY_FILES)
    if unexpected:
        fail(f"memoria local contiene entradas no gestionadas antes de adoptar Git: {chr(10).join(unexpected)}")

    with tempfile.TemporaryDirectory(prefix=".gitmem-adopt.", dir=memory_root) as temporary:
        # Validate the clone and every content conflict before copying into persistent memory.
        clone = Path(temporary)
        log(f"clonando temporalmente {repository} ({branch}) para validar adopcion")
        run("git", "clone", "--single-branch", "--branch", branch, "--", repository, str(clone))
        validate_identity(clone, repository, branch)
        static_files = []
        for relative in tracked_paths(clone):
            if relative in MEMORY_FILES:
                continue
            source = validate_static_path(clone, relative)
            target = data / relative
            if target.exists() or target.is_symlink():
                fail(f"fichero local inesperado colisiona con fichero estatico remoto: {relative}")
            static_files.append((relative, source, target))

        actions = []
        for name in MEMORY_FILES:
            local = data / name
            remote = clone / name
            if same_content(local, remote):
                actions.append((name, "same"))
            elif local.stat().st_size == 0 and remote.stat().st_size > 0:
                actions.append((name, "copy"))
            elif local.stat().st_size > 0 and remote.stat().st_size == 0:
                actions.append((name, "preserve"))
            else:
                fail(f"{name}: local y remoto contienen contenido distinto; resolver manualmente antes de habilitar Git memory")
            active = remote if actions[-1][1] == "copy" else local
            old = legacy / name
            if old.is_file() and old.stat().st_size and not same_content(old, active):
                fail(f"{old} contiene memoria distinta. Migra ese contenido deliberadamente y vuelve a ejecutar prepare-git-memory.py")

        for relative, source, target in static_files:
            target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            os.chown(target.parent, uid, gid)
            shutil.copy2(source, target)
            log(f"{relative}: fichero estatico adoptado desde Git")
        for name, action in actions:
            if action == "copy":
                shutil.copyfile(clone / name, data / name)
                log(f"{name}: local vacio; adoptado contenido remoto")
            elif action == "same":
                log(f"{name}: local y remoto coinciden")
            else:
                log(f"{name}: remoto vacio; contenido local preservado como cambio pendiente")
        shutil.move(str(clone / ".git"), str(data / ".git"))
        log("metadata Git adoptada sin sustituir el directorio persistente de memoria")


def changed_paths(tree: Path) -> list[str]:
    """List staged, unstaged, and untracked paths in a working tree."""
    changes = set()
    for args in (("diff", "--name-only", "-z"), ("diff", "--cached", "--name-only", "-z"),
                 ("ls-files", "--others", "--exclude-standard", "-z")):
        changes.update(os.fsdecode(path) for path in git(tree, *args, capture=True).stdout.split(b"\0") if path)
    return sorted(changes)


def main() -> None:
    """Validate prerequisites, adopt memory, and audit the resulting working tree."""
    if os.geteuid() != 0:
        fail("ejecutar como root")
    for command in ("git", "docker"):
        if shutil.which(command) is None:
            fail(f"falta el comando requerido: {command}")
    if not ENV_FILE.is_file():
        fail(f"falta {ENV_FILE}")
    if not LOCK_FILE.is_file():
        fail(f"Stack6 no esta preparado: falta {LOCK_FILE}; ejecutar primero 01-prepare.py")
    env_before, lock_before = sha256(ENV_FILE), sha256(LOCK_FILE)
    env = load_env(ENV_FILE)
    required = ("BASE_PATH", "HERMES_SERVICE", "HERMES_MEMORY_SERVICE", "HERMES_CONTAINER",
                "HERMES_UID", "HERMES_GID", "GITMEM_REPOSITORY", "GITMEM_BRANCH")
    for key in required:
        if not env.get(key):
            fail(f"falta {key} en {ENV_FILE}")
    base = env["BASE_PATH"]
    if not base.startswith("/"):
        fail("BASE_PATH debe ser una ruta absoluta")
    if base.rstrip("/") == "":
        fail("BASE_PATH no puede ser /")
    service, memory_service = env["HERMES_SERVICE"], env["HERMES_MEMORY_SERVICE"]
    for key, value in (("HERMES_SERVICE", service), ("HERMES_MEMORY_SERVICE", memory_service)):
        if not re.fullmatch(r"service_-_[A-Za-z0-9._-]+", value):
            fail(f"{key} debe seguir el patron service_-_*")
    if service == memory_service:
        fail("HERMES_MEMORY_SERVICE debe ser distinto de HERMES_SERVICE")
    branch, repository = env["GITMEM_BRANCH"], env["GITMEM_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch):
        fail("GITMEM_BRANCH contiene caracteres no admitidos")
    if re.match(r"https?://[^/]*@", repository):
        fail("GITMEM_REPOSITORY no debe incluir credenciales embebidas; usa Git credential/SSH externo")
    uid, gid = int(env["HERMES_UID"]), int(env["HERMES_GID"])
    base_path = Path(base).resolve()
    memory_root = base_path / memory_service
    data = memory_root / "data"
    legacy = base_path / service / "data/memories"

    step("Estado de Hermes")
    if subprocess.run(["docker", "inspect", env["HERMES_CONTAINER"]], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode == 0:
        running = run("docker", "inspect", "-f", "{{.State.Running}}", env["HERMES_CONTAINER"], capture=True).stdout.decode().strip()
        if running == "true":
            fail(f"el contenedor {env['HERMES_CONTAINER']} sigue corriendo; detener solo Hermes antes de preparar Git memory")
        log(f"{env['HERMES_CONTAINER']}: detenido")
    else:
        log(f"{env['HERMES_CONTAINER']}: no creado")

    step("Directorio persistente de memoria")
    for path in (memory_root, data):
        if path.is_symlink():
            fail(f"{path} no puede ser symlink")
        if path.exists() and not path.is_dir():
            fail(f"{path} no es un directorio")
        path.mkdir(mode=0o750, parents=True, exist_ok=True)
        os.chown(path, uid, gid)
        path.chmod(0o750)
    for name in MEMORY_FILES:
        path = data / name
        if path.is_symlink():
            fail(f"{path} no puede ser symlink")
        if path.exists() and not path.is_file():
            fail(f"{path} existe pero no es fichero normal")
        if not path.exists():
            path.touch(mode=0o640)
            os.chown(path, uid, gid)
            log(f"creado fichero local vacio: {name}")

    step("Working tree Git")
    adopt(memory_root, data, legacy, repository, branch, uid, gid)
    origin, actual_branch = validate_identity(data, repository, branch)

    step("Memoria legacy")
    for name in MEMORY_FILES:
        old = legacy / name
        if old.is_file() and old.stat().st_size:
            if not same_content(old, data / name):
                fail(f"{old} contiene memoria distinta. Migra ese contenido deliberadamente y vuelve a ejecutar prepare-git-memory.py")
            log(f"{name}: legacy coincide con memoria activa")
        else:
            log(f"{name}: sin memoria legacy no vacia")

    for root, directories, files in os.walk(data, followlinks=False):
        os.chown(root, uid, gid)
        for name in directories + files:
            os.chown(Path(root) / name, uid, gid, follow_symlinks=False)
    data.chmod(0o750)
    for name in MEMORY_FILES:
        (data / name).chmod(0o640)

    step("Auditoria")
    if not (data / ".git").is_dir() or (data / ".git").is_symlink():
        fail(".git ausente o invalido")
    for path, mode in ((data, 0o750), *((data / name, 0o640) for name in MEMORY_FILES)):
        info = path.stat()
        if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, gid, mode):
            fail(f"propietario/permisos inesperados en {path}")
    changes = changed_paths(data)
    for path in changes:
        if path not in MEMORY_FILES:
            fail(f"cambio no autorizado tras adopcion: {path}")
    if sha256(ENV_FILE) != env_before:
        fail(".env ha cambiado durante prepare-git-memory.py")
    if sha256(LOCK_FILE) != lock_before:
        fail(".lock ha cambiado durante prepare-git-memory.py")
    log(f"working tree: {data}")
    log(f"origin: {origin}")
    log(f"branch: {actual_branch}")
    log("MEMORY.md / USER.md: versionados y validos")
    log("ficheros estaticos versionados: permitidos solo si permanecen sin cambios")
    log("cambios locales de memoria preservados; el sidecar podra sincronizarlos de forma conservadora" if changes else "working tree alineado con Git")
    log(".env y .lock inmutables: OK")
    print("\nGit-backed memory preparada y auditada.\n\nEste script NO ha ejecutado pull/merge/rebase/commit/push/reset.\nLa sincronizacion se habilita separadamente mediante el profile git-memory.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        fail(str(error))
