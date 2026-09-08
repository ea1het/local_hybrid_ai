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

The two files under `config/` are the real source files for the stack. `01-prepare.sh` renders them by replacing only the values that come from `.env`; there is no complete `app.ini` embedded in Bash.

## `.env`

Stack4 consumes the central environment through `.env -> ../.env`. Relevant values include:

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
```

`GITEA_INTERNAL_TOKEN` and `GITEA_JWT_SECRET` are persistent Gitea secrets and must not be rotated accidentally.

The Actions runner registration token is **not part of the permanent `.env` contract**. Stack4 owns it as persistent runtime state:

```text
${BASE_PATH}/service_-_gitea-runner/secret/registration-token
```

`01-prepare.sh` preserves an existing runtime token. During migration of an older deployment it may adopt the former `GITEA_RUNNER_REGISTRATION_TOKEN` value from `.env` once. On a fresh deployment, when neither runtime token nor legacy value exists, Stack4 generates the token once and persists it outside Git and outside `.env`.

Both Gitea and `gitea-runner` receive only `GITEA_RUNNER_REGISTRATION_TOKEN_FILE`, pointing to a read-only mount of that runtime secret. The token value itself is not injected into container environment variables.

## Operational paths

```text
${BASE_PATH}/service_-_gitea/config
${BASE_PATH}/service_-_gitea/data
${BASE_PATH}/service_-_gitea-runner/data
${BASE_PATH}/service_-_gitea-runner/secret
```

The runner keeps its `.runner` identity and `config.yaml` in its `data` directory. The registration token is stored separately in `secret/registration-token`.

## Runtime policy

`01-prepare.sh` works on the current runtime layout under `${BASE_PATH}` and does not automatically migrate unrelated legacy directories.

It replaces managed configuration while preserving `service_-_gitea/data`, the persistent runner `.runner` identity and the runtime-owned registration token. Legacy runner `ca-certificates.crt` and `certificates.txt` files are removed because they belong to the previous TLS architecture.

Stack4 does not create the shared Docker network. Stack0 owns `redlocal`; Stack4 verifies that it already exists.

## Preparation lock contract

`.lock` means only that `01-prepare.sh` completed successfully and the stack is prepared. It does not mean migrations have run, the administrator has been ensured, or Gitea/runner are running.

`01-prepare.sh` creates `.lock`. `02-run.sh` requires it and performs the remaining installation/start phase without owning or rewriting the lock.

## Installation / refactor

```bash
cd /opt/docker/stacks/stack4_-_gitea
sudo ./01-prepare.sh
sudo ./02-run.sh
```

`01-prepare.sh` validates the Stack0 network dependency, prepares the persistent runner token, renders managed configuration and creates `.lock`.

`02-run.sh`:

1. requires the preparation lock;
2. validates Compose;
3. downloads the images;
4. runs Gitea migrations;
5. ensures the configured administrator exists;
6. starts Gitea and the runner;
7. verifies that the runner has created or recovered its persistent `.runner` identity.

## Atomicity contract

Stack4 is atomic once Stack0 is available:

```text
Stack4 requires: Stack0
Stack4 owns: Gitea, gitea-runner, their runtime data and runner registration secret
```

No externally provisioned runner-registration token is required for a fresh installation.

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

This may replace configuration and rerun migrations, but it preserves Gitea data, runner identity and the runtime registration token.
