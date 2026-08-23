# Stack5 — Dockhand

Minimal stack for Dockhand. The `docker-compose.yml` remains unchanged from a functional standpoint.

Dockhand:

- is connected to `redlocal`;
- exposes port 3000 only within Docker;
- is published externally by HAProxy as `https://homelab.casa.lan`;
- uses the existing external Docker volume `dockhand_data`.

## Structure

```text
stack5_-_dockhand/
├── .env
├── docker-compose.yml
├── 01-prepare.sh
└── README.md
```

The `.env` currently contains only:

```text
BASE_PATH=/opt/docker
```

This is kept so that all stacks follow the same contract. Dockhand does not currently need any Compose environment variables.

## Preparation

```bash
cd /opt/docker/stack5_-_dockhand
sudo ./01-prepare.sh
```

The script validates:

- the stack location relative to `BASE_PATH`;
- the presence/driver of `redlocal`;
- the existence of the external volume `dockhand_data`;
- the Compose syntax/configuration.

It does not create or modify `dockhand_data`.

When complete, it creates `.lock`.

## Startup

```bash
docker compose up -d
docker compose ps
docker compose logs -f dockhand
```

## Rebuild

```bash
rm .lock
sudo ./01-prepare.sh
```

There is no `service_-_dockhand` directory because this deployment persists exclusively through the external Docker volume `dockhand_data`.
