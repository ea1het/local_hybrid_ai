# Stack4 — Gitea

Gitea sirve **HTTP** dentro de `redlocal` y HAProxy proporciona el HTTPS público.

```text
HAProxy -> http://gitea:3000
```

El SSH integrado de Gitea se publica directamente en el host en el puerto configurado, actualmente 2222.

El runner también accede directamente a:

```text
http://gitea:3000/
```

No usa certificados, CA personalizada ni `NODE_EXTRA_CA_CERTS`.

## Estructura

```text
stack4_-_gitea/
├── .env
├── docker-compose.yml
├── 01-prepare.sh
├── 02-run.sh
├── README.md
└── config/
    ├── gitea/
    │   └── app.ini
    └── gitea-runner/
        └── config.yaml
```

Los dos ficheros de `config/` son fuentes reales del stack. `01-prepare.sh` los renderiza sustituyendo únicamente los valores que proceden del `.env`; ya no existe un `app.ini` completo embebido en Bash.

## `.env`

Contiene configuración y secretos tanto de Compose como de los scripts. Entre otros:

```text
STACKS_ROOT
BASE_PATH
GITEA_IMAGE
GITEA_CONTAINER_NAME
GITEA_UID
GITEA_GID
GITEA_SSH_BIND
GITEA_SSH_PORT
GITEA_DOCKER_NETWORK
GITEA_DOMAIN
GITEA_ROOT_URL
GITEA_SSH_DOMAIN
GITEA_TIMEZONE
GITEA_INTERNAL_TOKEN
GITEA_JWT_SECRET
GITEA_ADMIN_USERNAME
GITEA_ADMIN_EMAIL
GITEA_ADMIN_PASSWORD
GITEA_RUNNER_IMAGE
GITEA_RUNNER_NAME
GITEA_RUNNER_INSTANCE_URL
GITEA_RUNNER_REGISTRATION_TOKEN
```

`GITEA_INTERNAL_TOKEN` y `GITEA_JWT_SECRET` proceden de la instancia existente y son secretos persistentes. No deben rotarse accidentalmente.

## Rutas operativas

```text
${BASE_PATH}/service_-_gitea/config
${BASE_PATH}/service_-_gitea/data
${BASE_PATH}/service_-_gitea-runner/data
```

El runner mantiene en su `data` la identidad `.runner` además de `config.yaml`.

## Política de runtime

`01-prepare.sh` trabaja sobre el layout runtime actual bajo `${BASE_PATH}` y no migra automáticamente directorios antiguos.

Sustituye la configuración gestionada preservando `service_-_gitea/data` y la identidad persistente `.runner` del runner. Los antiguos `ca-certificates.crt` y `certificates.txt` se eliminan porque pertenecen a la arquitectura TLS anterior.

## Contrato del lock de preparación

`.lock` significa únicamente que `01-prepare.sh` terminó correctamente y el stack está preparado. No significa que se hayan ejecutado las migraciones, que el administrador esté asegurado ni que Gitea/runner estén arrancados.

`01-prepare.sh` crea `.lock`. `02-run.sh` lo requiere y ejecuta el resto de la instalación/arranque sin ser propietario del lock ni reescribirlo.

## Instalación / refactor

```bash
cd /opt/docker/stacks/stack4_-_gitea
sudo ./01-prepare.sh
sudo ./02-run.sh
```

`01-prepare.sh` valida y renderiza la configuración gestionada y después crea `.lock`.

`02-run.sh`:

1. requiere el lock de preparación;
2. valida Compose;
3. descarga las imágenes;
4. ejecuta las migraciones de Gitea;
5. asegura que existe el administrador configurado;
6. arranca Gitea y el runner.

## Operación normal

Después de la instalación no se usa `02-run.sh` como comando habitual de arranque. Se utiliza Docker Compose:

```bash
docker compose up -d
docker compose down
docker compose restart gitea
docker compose logs -f
```

## Reconstrucción de configuración

```bash
rm .lock
sudo ./01-prepare.sh
sudo ./02-run.sh
```

Esto puede sustituir configuración y volver a ejecutar migraciones, pero no vacía los datos de Gitea.
