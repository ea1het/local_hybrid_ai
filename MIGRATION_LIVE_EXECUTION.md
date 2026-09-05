# Phase 1 live-execution notes

This deployment is already running. Treat Phase 1 as a live migration, not a cold installation.

These notes complement `MIGRATION_PHASE1.md` and take precedence whenever a checkpoint involves stopping or recreating a running service.

## General rule

Do all file and `.env` edits while the current containers remain running. Stop a service only immediately before a prepare/recreate step that requires it to be stopped, and bring it back before continuing to the next independent checkpoint.

Do not run `docker compose down` merely to edit `.env` or inspect configuration.

Prefer stopping/recreating only the affected service when that is sufficient. Use full-stack `down` only when the stack topology itself requires complete teardown.

## Stack3 / LiteLLM

While editing `/opt/docker/stack3_-_litellm/.env`, keep LiteLLM running.

After the `.env` has the pinned values:

```dotenv
LITELLM_IMAGE=ghcr.io/berriai/litellm-database
LITELLM_VERSION=1.99.1
```

validate first without stopping the running container:

```bash
cd /opt/docker/stack3_-_litellm
docker compose config --quiet
docker compose config | grep -A2 'image:'
```

Only then enter the LiteLLM maintenance window:

```bash
docker compose stop litellm
rm -f .lock
sudo ./01-prepare.sh
sudo ./02-postgres.sh
docker compose up -d --force-recreate litellm
```

Immediately validate:

```bash
docker compose ps
docker compose logs --tail=100 litellm
docker inspect litellm --format '{{.Config.Image}}'
```

Do not continue to MCP configuration until existing model inference works again.

A full `docker compose down` is not required for this Stack3 version-pin step.

## Stack6 / Hermes

Keep Hermes and `hermes-sandbox` running while preparing external prerequisites such as:

- the LiteLLM Trivago MCP server
- the dedicated Hermes MCP virtual key
- the private Gitea memory repository
- Stack6 `.env` edits

Stop Stack6 only when ready to run `01-prepare.sh` and `04-gitmem.sh`:

```bash
cd /opt/docker/stack6_-_hermes
docker compose stop
```

Then perform the complete stopped-state sequence before restarting:

```bash
rm -f .lock
sudo ./01-prepare.sh
sudo bash ./04-gitmem.sh
docker compose up -d --build --force-recreate
```

There should be no intermediate Hermes restart between `01-prepare.sh` and `04-gitmem.sh`.

The memory bind uses `create_host_path: false`, so an accidental start before `04-gitmem.sh` should fail rather than create an empty memory directory.

## Rollback principle

Keep the previously running image locally until each checkpoint is accepted. If a recreate fails, restore only the affected stack; do not reset unrelated stacks or delete PostgreSQL/Git persistent data.
