# Stack4 — Gitea

Gitea serves **HTTP** inside `redlocal`, and HAProxy provides the public HTTPS endpoint.

```text
HAProxy -> http://gitea:3000
```

Gitea's built-in SSH is published directly on the host on the configured port, currently 2222.

The runner also accesses directly:

```text
http://gitea:3000/
```

It does not use custom certificates, a custom CA, or `NODE_EXTRA_CA_CERTS`.

## Structure

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

The two files under `config/` are the real source files for the stack. `01-prepare.sh` renders them by replacing only the values that come from `.env`; there is no longer a complete `app.ini` embedded in Bash.

## `.env`

It contains configuration and secrets for both Compose and the scripts. Among others:

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

`GITEA_INTERNAL_TOKEN` and `GITEA_JWT_SECRET` come from the existing instance and are persistent secrets. They should not be rotated accidentally.

## Operational paths

```text
${BASE_PATH}/service_-_gitea/config
${BASE_PATH}/service_-_gitea/data
${BASE_PATH}/service_-_gitea-runner/data
```

The runner keeps its `.runner` identity and `config.yaml` in its `data` directory.

## Migration from the previous structure

`01-prepare.sh` migrates, if they exist and the destination is free:

```text
/opt/docker/gitea/data   -> /opt/docker/service_-_gitea/data
/opt/docker/gitea/runner -> /opt/docker/service_-_gitea-runner/data
```

It then replaces the configuration completely. The old runner `ca-certificates.crt` and `certificates.txt` are removed because they belong to the previous TLS architecture.

It never deletes `service_-_gitea/data` or the persistent `.runner` identity.

## Installation / refactor

```bash
cd /opt/docker/stack4_-_gitea
sudo ./01-prepare.sh
sudo ./02-run.sh
```

`01-prepare.sh` does not create `.lock`, because the second step is still pending.

`02-run.sh`:

1. validates Compose;
2. downloads the images;
3. runs Gitea migrations;
4. ensures the configured administrator exists;
5. starts Gitea and the runner;
6. creates `.lock`.

With `.lock` present, both scripts exit immediately without modifying anything.

## Normal operation

After installation, `02-run.sh` is not used as the normal startup command. Docker Compose is used instead:

```bash
docker compose up -d
docker compose down
docker compose restart gitea
docker compose logs -f
```

## Configuration rebuild

```bash
rm .lock
sudo ./01-prepare.sh
sudo ./02-run.sh
```

This may replace the configuration and rerun migrations, but it does not empty Gitea data.
