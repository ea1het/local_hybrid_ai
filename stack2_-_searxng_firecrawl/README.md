# Stack2 — SearXNG + Firecrawl

Search and web extraction stack. None of its services publish ports directly to the host.

- SearXNG is exposed to the user only through HAProxy at `https://buscar.casa.lan/`.
- Firecrawl API is an internal `redlocal` service at `http://firecrawl-api:3002`.
- Firecrawl accesses SearXNG directly at `http://searxng:8080`.
- Redis, RabbitMQ and PostgreSQL are internal.

## Structure

```text
stack2_-_searxng_firecrawl/
├── .env
├── docker-compose.yml
├── 01-prepare.sh
├── README.md
└── config/
    └── searxng/
        ├── settings.yml
        └── limiter.toml
```

`limiter.toml` is intentionally kept as an empty file.

## `.env`

Current variables:

```text
BASE_PATH
SEARXNG_SECRET
SEARXNG_BASE_URL
REDIS_PASSWORD
RABBITMQ_USER
RABBITMQ_PASSWORD
POSTGRES_USER
POSTGRES_PASSWORD
POSTGRES_DB
```

`SEARXNG_PORT` and `FIRECRAWL_PORT` no longer exist, because Compose does not publish those ports.

The public URL must be:

```text
SEARXNG_BASE_URL=https://buscar.casa.lan/
```

Secrets must be complete before running the script. `01-prepare.sh` does not generate them.

## Persistence

```text
${BASE_PATH}/service_-_searxng/config
${BASE_PATH}/service_-_searxng/data
${BASE_PATH}/service_-_firecrawl-redis/data
${BASE_PATH}/service_-_firecrawl-rabbitmq/data
${BASE_PATH}/service_-_firecrawl-postgres/data
```

The script migrates the old paths without the `service_-_` prefix when the destination does not exist. If it detects both source and destination at the same time, it stops to avoid automatically choosing between two possible data sets.

The `data` directories are never deleted. They can only be created and their ownership adjusted.

## Preparation

```bash
cd /opt/docker/stack2_-_searxng_firecrawl
sudo ./01-prepare.sh
```

Without `.lock`, the script replaces `service_-_searxng/config` with the stack source content, validates the network and Compose, and finally creates `.lock`.

Then:

```bash
docker compose up -d
docker compose ps
docker compose logs -f
```

## Internal endpoints

```text
SearXNG:        http://searxng:8080
Firecrawl API: http://firecrawl-api:3002
PostgreSQL:    firecrawl-postgres:5432
Redis:         firecrawl-redis:6379
RabbitMQ:      firecrawl-rabbitmq:5672
```

## Configuration rebuild

```bash
rm .lock
sudo ./01-prepare.sh
```

This rewrites the configuration but does not delete persistent data.

