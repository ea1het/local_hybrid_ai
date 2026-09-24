#!/usr/bin/env python3
"""
02-copycacert.py

Instala la CA local en m92p, actualiza el trust store del host, configura
el contenedor LiteLLM para usar el bundle de CAs del host, recrea LiteLLM
y verifica TLS contra https://mlx.casa.lan.

Suposiciones:
  - La CA pública ya está copiada en:
      /opt/docker/stacks/stack0_-_platform
  - El contenedor se llama "litellm".
  - LiteLLM fue levantado con Docker Compose.

Uso:
  sudo ./02-copycacert.py

Opcional:
  sudo ./02-copycacert.py --ca /ruta/rootCA.pem
  sudo ./02-copycacert.py --compose /ruta/docker-compose.yml
  sudo ./02-copycacert.py --container litellm
  sudo ./02-copycacert.py --url https://mlx.casa.lan/v1/models

Qué hace:
  1. Localiza y valida la CA.
  2. La instala en /usr/local/share/ca-certificates/casa-local-ca.crt.
  3. Ejecuta update-ca-certificates.
  4. Verifica el bundle del host con openssl.
  5. Localiza el Compose de LiteLLM mediante labels Docker (o --compose).
  6. Hace backup del Compose.
  7. Añade al servicio litellm:
       - bind mount del bundle del host
       - SSL_CERT_FILE
       - REQUESTS_CA_BUNDLE
  8. Valida el Compose.
  9. Recrea solo el servicio litellm.
 10. Verifica el mount, las variables y TLS hacia mlx.casa.lan.

Es idempotente: puede ejecutarse varias veces.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PLATFORM_DIR = Path("/opt/docker/stacks/stack0_-_platform")
DEST_CA = Path("/usr/local/share/ca-certificates/casa-local-ca.crt")
HOST_CA_BUNDLE = Path("/etc/ssl/certs/ca-certificates.crt")
CONTAINER_CA_BUNDLE = "/etc/ssl/certs/casa-ca-bundle.pem"

DEFAULT_CA_NAMES = (
    "casa-local-ca.crt",
    "rootCA.pem",
    "rootCA.crt",
    "casa-local-ca.pem",
)


def die(message: str, code: int = 1) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            text=True,
            check=True,
            capture_output=capture,
        )
    except subprocess.CalledProcessError as exc:
        if capture:
            if exc.stdout:
                print(exc.stdout, file=sys.stderr, end="")
            if exc.stderr:
                print(exc.stderr, file=sys.stderr, end="")
        raise


def require_root() -> None:
    if os.geteuid() != 0:
        die("Ejecuta el script con sudo/root.")


def require_commands() -> None:
    required = ("docker", "openssl", "update-ca-certificates")
    missing = [cmd for cmd in required if shutil.which(cmd) is None]
    if missing:
        die("Faltan comandos requeridos: " + ", ".join(missing))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ca", type=Path, help="Ruta explícita al certificado CA")
    parser.add_argument("--compose", type=Path, help="Ruta explícita al Compose de LiteLLM")
    parser.add_argument("--container", default="litellm", help="Nombre del contenedor LiteLLM")
    parser.add_argument(
        "--url",
        default="https://mlx.casa.lan/v1/models",
        help="URL HTTPS utilizada para verificar TLS",
    )
    return parser.parse_args()


def find_ca(explicit: Path | None) -> Path:
    if explicit:
        source = explicit.resolve()
        if not source.is_file():
            die(f"No existe el certificado CA: {source}")
        return source

    for name in DEFAULT_CA_NAMES:
        candidate = PLATFORM_DIR / name
        if candidate.is_file():
            return candidate

    if not PLATFORM_DIR.is_dir():
        die(f"No existe el directorio esperado: {PLATFORM_DIR}")

    candidates = sorted(
        p for p in PLATFORM_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".crt", ".pem", ".cer"}
    )

    if len(candidates) == 1:
        return candidates[0]

    if not candidates:
        die(
            f"No encontré ningún .crt/.pem/.cer en {PLATFORM_DIR}. "
            "Usa --ca /ruta/al/rootCA.pem si tiene otro nombre."
        )

    names = "\n  - ".join(str(p) for p in candidates)
    die(
        "Hay varios certificados posibles y no voy a adivinar cuál es la CA.\n"
        f"  - {names}\n"
        "Usa --ca /ruta/al/rootCA.pem."
    )


def validate_ca(source: Path) -> None:
    print("\n== 1/7 Validando CA ==")
    result = run(
        [
            "openssl",
            "x509",
            "-in",
            str(source),
            "-noout",
            "-subject",
            "-issuer",
            "-dates",
            "-fingerprint",
            "-sha256",
            "-text",
        ],
        capture=True,
    )

    if "CA:TRUE" not in result.stdout:
        die(f"El certificado no parece ser una CA (no contiene CA:TRUE): {source}")

    summary = run(
        [
            "openssl",
            "x509",
            "-in",
            str(source),
            "-noout",
            "-subject",
            "-issuer",
            "-dates",
            "-fingerprint",
            "-sha256",
        ],
        capture=True,
    )
    print(summary.stdout, end="")


def install_ca_on_host(source: Path) -> None:
    print("\n== 2/7 Instalando CA en el host ==")
    DEST_CA.parent.mkdir(parents=True, exist_ok=True)

    run(["install", "-m", "0644", str(source), str(DEST_CA)])
    run(["update-ca-certificates"])

    if not HOST_CA_BUNDLE.is_file():
        die(f"No existe el bundle del sistema esperado: {HOST_CA_BUNDLE}")

    verify = run(
        [
            "openssl",
            "verify",
            "-CAfile",
            str(HOST_CA_BUNDLE),
            str(DEST_CA),
        ],
        capture=True,
    )
    print(verify.stdout, end="")


def docker_label(container: str, label: str) -> str:
    result = run(
        [
            "docker",
            "inspect",
            container,
            "--format",
            f'{{{{ index .Config.Labels "{label}" }}}}',
        ],
        capture=True,
    )
    return result.stdout.strip()


def find_compose(container: str, explicit: Path | None) -> tuple[Path, Path]:
    print("\n== 3/7 Localizando Docker Compose de LiteLLM ==")

    if explicit:
        compose = explicit.resolve()
        if not compose.is_file():
            die(f"No existe el Compose indicado: {compose}")
        return compose.parent, compose

    workdir_raw = docker_label(container, "com.docker.compose.project.working_dir")
    config_files_raw = docker_label(container, "com.docker.compose.project.config_files")

    if not workdir_raw:
        die(f"El contenedor {container!r} no tiene el label " "com.docker.compose.project.working_dir. Usa --compose.")

    workdir = Path(workdir_raw)
    candidates: list[Path] = []

    if config_files_raw:
        for item in config_files_raw.split(","):
            item = item.strip()
            if not item:
                continue
            p = Path(item)
            if not p.is_absolute():
                p = workdir / p
            if p.is_file():
                candidates.append(p)

    if not candidates:
        for name in (
            "compose.yaml",
            "compose.yml",
            "docker-compose.yaml",
            "docker-compose.yml",
        ):
            p = workdir / name
            if p.is_file():
                candidates.append(p)

    for compose in candidates:
        text = compose.read_text(encoding="utf-8")
        if re.search(r"(?m)^  litellm:\s*$", text):
            print(f"Working directory: {workdir}")
            print(f"Compose:           {compose}")
            return workdir, compose

    die("No pude localizar un Compose que contenga el servicio 'litellm'. " "Usa --compose /ruta/docker-compose.yml.")


def find_service_bounds(lines: list[str]) -> tuple[int, int]:
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^  litellm:\s*$", line):
            start = i
            break

    if start is None:
        die("No se encontró el servicio 'litellm:' en el Compose.")

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^  [A-Za-z0-9_.-]+:\s*$", lines[i]):
            end = i
            break

    return start, end


def patch_compose(compose: Path) -> bool:
    print("\n== 4/7 Configurando trust bundle en LiteLLM ==")

    original = compose.read_text(encoding="utf-8")
    had_final_newline = original.endswith("\n")
    lines = original.splitlines()

    volume_value = f"{HOST_CA_BUNDLE}:{CONTAINER_CA_BUNDLE}:ro"
    volume_line = f"      - {volume_value}"

    # --- volumes ---
    start, end = find_service_bounds(lines)
    volume_exists = any(volume_value in lines[i] for i in range(start + 1, end))

    if not volume_exists:
        volumes_idx = next(
            (i for i in range(start + 1, end) if re.match(r"^    volumes:\s*$", lines[i])),
            None,
        )

        if volumes_idx is None:
            environment_idx = next(
                (i for i in range(start + 1, end) if re.match(r"^    environment:\s*$", lines[i])),
                end,
            )
            lines[environment_idx:environment_idx] = [
                "    volumes:",
                volume_line,
                "",
            ]
        else:
            insert_at = end
            for i in range(volumes_idx + 1, end):
                if re.match(r"^    [A-Za-z0-9_.-]+:\s*", lines[i]):
                    insert_at = i
                    break
            lines.insert(insert_at, volume_line)

    # --- environment ---
    start, end = find_service_bounds(lines)
    env_idx = next(
        (i for i in range(start + 1, end) if re.match(r"^    environment:\s*$", lines[i])),
        None,
    )

    desired_env = {
        "SSL_CERT_FILE": CONTAINER_CA_BUNDLE,
        "REQUESTS_CA_BUNDLE": CONTAINER_CA_BUNDLE,
    }

    if env_idx is None:
        insert_at = end
        for i in range(start + 1, end):
            if re.match(
                r"^    (networks|depends_on|healthcheck|logging):\s*$",
                lines[i],
            ):
                insert_at = i
                break

        block = ["    environment:"]
        for key, value in desired_env.items():
            block.append(f'      {key}: "{value}"')
        block.append("")
        lines[insert_at:insert_at] = block
    else:
        start, end = find_service_bounds(lines)

        for key, value in desired_env.items():
            pattern = re.compile(rf"^      {re.escape(key)}:\s*.*$")
            found = False

            for i in range(env_idx + 1, end):
                if pattern.match(lines[i]):
                    lines[i] = f'      {key}: "{value}"'
                    found = True
                    break

            if not found:
                lines.insert(env_idx + 1, f'      {key}: "{value}"')

    updated = "\n".join(lines)
    if had_final_newline:
        updated += "\n"

    if updated == original:
        print("Compose ya estaba configurado; no hay cambios.")
        return False

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = compose.with_name(f"{compose.name}.bak.{stamp}")
    shutil.copy2(compose, backup)
    print(f"Backup creado: {backup}")

    compose.write_text(updated, encoding="utf-8")

    try:
        run(
            ["docker", "compose", "-f", str(compose), "config"],
            cwd=compose.parent,
            capture=True,
        )
    except subprocess.CalledProcessError:
        shutil.copy2(backup, compose)
        die("El Compose modificado no valida. " f"Se restauró automáticamente {backup}.")

    print("Compose actualizado y validado.")
    return True


def recreate_litellm(workdir: Path, compose: Path) -> None:
    print("\n== 5/7 Recreando solo LiteLLM ==")
    run(
        [
            "docker",
            "compose",
            "-f",
            str(compose),
            "up",
            "-d",
            "--force-recreate",
            "litellm",
        ],
        cwd=workdir,
    )


def verify_container(container: str) -> None:
    print("\n== 6/7 Verificando variables y bundle dentro de LiteLLM ==")

    result = run(
        [
            "docker",
            "exec",
            container,
            "sh",
            "-lc",
            (
                'echo "SSL_CERT_FILE=$SSL_CERT_FILE"; '
                'echo "REQUESTS_CA_BUNDLE=$REQUESTS_CA_BUNDLE"; '
                f'ls -lh "{CONTAINER_CA_BUNDLE}"'
            ),
        ],
        capture=True,
    )
    print(result.stdout, end="")

    expected = (
        f"SSL_CERT_FILE={CONTAINER_CA_BUNDLE}",
        f"REQUESTS_CA_BUNDLE={CONTAINER_CA_BUNDLE}",
    )
    for item in expected:
        if item not in result.stdout:
            die(f"No se encontró dentro del contenedor: {item}")


def verify_tls(container: str, url: str) -> None:
    print("\n== 7/7 Verificando TLS LiteLLM -> Caddy -> oMLX ==")

    python_code = "\n".join(
        [
            "import urllib.error",
            "import urllib.request",
            f"url = {url!r}",
            "try:",
            "    with urllib.request.urlopen(url, timeout=10) as r:",
            "        print(f'TLS OK - HTTP {r.status}')",
            "        raise SystemExit(0)",
            "except urllib.error.HTTPError as e:",
            "    print(f'TLS OK - HTTP {e.code}')",
            "    raise SystemExit(0)",
            "except Exception as e:",
            "    print(f'TLS FAILED - {type(e).__name__}: {e}')",
            "    raise SystemExit(1)",
        ]
    )

    result = run(
        [
            "docker",
            "exec",
            container,
            "python",
            "-c",
            python_code,
        ],
        capture=True,
    )
    print(result.stdout, end="")


def main() -> None:
    args = parse_args()

    require_root()
    require_commands()

    source = find_ca(args.ca)
    print(f"CA origen: {source}")

    validate_ca(source)
    install_ca_on_host(source)

    workdir, compose = find_compose(args.container, args.compose)
    patch_compose(compose)

    recreate_litellm(workdir, compose)
    verify_container(args.container)
    verify_tls(args.container, args.url)

    print("\nSUCCESS")
    print("CASA Local CA instalada en m92p.")
    print("LiteLLM usa el bundle de confianza del host.")
    print(f"Bundle host:      {HOST_CA_BUNDLE}")
    print(f"Bundle container: {CONTAINER_CA_BUNDLE}")
    print(f"TLS probado con:  {args.url}")
    print("")
    print("Nota: un HTTP 401/403 en la prueba TLS se considera correcto:")
    print("demuestra que DNS + TLS + CA + Caddy funcionan y que oMLX respondió.")


if __name__ == "__main__":
    main()
