# Stack2 — SearXNG + Firecrawl

Stack de búsqueda y extracción web. Ninguno de sus servicios publica puertos directamente en el host.

- SearXNG se expone al usuario únicamente mediante HAProxy en `https://buscar.casa.lan/`.
- Firecrawl API es un servicio interno de `redlocal` en `http://firecrawl-api:3002`.
- Firecrawl accede a SearXNG directamente en `http://searxng:8080`.
- Redis, RabbitMQ y PostgreSQL son internos.

## Estructura

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

`limiter.toml` se mantiene intencionalmente como fichero vacío.

## `.env`

Variables actuales:

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

No existen ya `SEARXNG_PORT` ni `FIRECRAWL_PORT`, porque el Compose no publica esos puertos.

La URL pública debe ser:

```text
SEARXNG_BASE_URL=https://buscar.casa.lan/
```

Los secretos deben estar completos antes de ejecutar el script. `01-prepare.sh` no los genera.

## Persistencia

```text
${BASE_PATH}/service_-_searxng/config
${BASE_PATH}/service_-_searxng/data
${BASE_PATH}/service_-_firecrawl-redis/data
${BASE_PATH}/service_-_firecrawl-rabbitmq/data
${BASE_PATH}/service_-_firecrawl-postgres/data
```

El script migra las antiguas rutas sin prefijo `service_-_` cuando el destino no existe. Si detecta origen y destino simultáneamente, para para evitar elegir automáticamente entre dos posibles conjuntos de datos.

Los directorios `data` nunca se borran. Solo pueden crearse y ajustarse sus propietarios.

## Preparación

```bash
cd /opt/docker/stack2_-_searxng_firecrawl
sudo ./01-prepare.sh
```

Sin `.lock`, el script sustituye `service_-_searxng/config` por el contenido fuente del stack, valida la red y el Compose y finalmente crea `.lock`.

Después:

```bash
docker compose up -d
docker compose ps
docker compose logs -f
```

## Endpoints internos

```text
SearXNG:        http://searxng:8080
Firecrawl API: http://firecrawl-api:3002
PostgreSQL:    firecrawl-postgres:5432
Redis:         firecrawl-redis:6379
RabbitMQ:      firecrawl-rabbitmq:5672
```

## Reconstrucción de configuración

```bash
rm .lock
sudo ./01-prepare.sh
```

Esto reescribe configuración, pero no elimina datos persistentes.

