# Stack5 — Dockhand

Minimal stack for Dockhand.

Dockhand:

- is connected to the shared Stack0 network;
- exposes port 3000 only within Docker;
- is published externally by HAProxy as `https://homelab.casa.lan` when Stack1 is present;
- persists its application state in the Stack5-owned Docker volume `dockhand_data`.

## Structure

```text
stack5_-_dockhand/
├── .env
├── docker-compose.yml
├── 01-prepare.sh
├── manifest.json
└── README.md
```

The `.env` contains only the shared platform contract required by this stack:

```text
STACKS_ROOT=/opt/docker/stacks
BASE_PATH=/opt/docker/runtime
NETWORK_NAME=redlocal
```

Dockhand does not require additional application-specific environment variables.

## Atomicity contract

Stack5 requires only Stack0.

Stack0 owns the shared Docker network. Stack5 verifies that network but does not create it.

Stack5 owns `dockhand_data`:

- if the volume already exists, it is preserved unchanged;
- if it does not exist, `01-prepare.sh` creates it;
- preparation never deletes or recreates an existing volume;
- normal Compose shutdown does not remove the external volume.

The volume remains declared `external: true` in Compose so its lifecycle stays explicit and is not coupled to `docker compose down`.

## Preparation

```bash
cd /opt/docker/stacks/stack5_-_dockhand
sudo ./01-prepare.sh
```

The script validates:

- the stack location relative to `STACKS_ROOT`;
- the presence/driver of the shared `NETWORK_NAME` created by Stack0;
- the presence of `dockhand_data`, creating it only when absent;
- the Compose syntax/configuration.

When complete, it creates `.lock` with the common meaning `PREPARED`.

## Startup

```bash
docker compose up -d
docker compose ps
docker compose logs -f dockhand
```

## Rebuild / re-prepare

```bash
rm .lock
sudo ./01-prepare.sh
```

Re-preparation preserves `dockhand_data` and therefore Dockhand state.

There is no `service_-_dockhand` directory because this deployment persists exclusively through the Stack5-owned named Docker volume `dockhand_data`.
