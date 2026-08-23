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

## Migración desde la estructura anterior

`01-prepare.sh` migra, si existen y el destino está libre:

```text
/opt/docker/gitea/data   -> /opt/docker/service_-_gitea/data
/opt/docker/gitea/runner -> /opt/docker/service_-_gitea-runner/data
```

Después sustituye completamente la configuración. Los antiguos `ca-certificates.crt` y `certificates.txt` del runner se eliminan porque pertenecen a la arquitectura TLS anterior.

Nunca elimina `service_-_gitea/data` ni la identidad persistente `.runner`.

## Instalación / refactor

```bash
cd /opt/docker/stack4_-_gitea
sudo ./01-prepare.sh
sudo ./02-run.sh
```

`01-prepare.sh` no crea `.lock`, porque aún falta el segundo paso.

`02-run.sh`:

1. valida el Compose;
2. descarga las imágenes;
3. ejecuta las migraciones de Gitea;
4. asegura que existe el administrador configurado;
5. arranca Gitea y el runner;
6. crea `.lock`.

Con `.lock` presente, ambos scripts salen inmediatamente sin modificar nada.

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
