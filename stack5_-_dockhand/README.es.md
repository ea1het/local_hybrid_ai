# Stack5 — Dockhand

Stack mínimo para Dockhand. El `docker-compose.yml` se mantiene sin cambios funcionales.

Dockhand:

- está conectado a `redlocal`;
- expone 3000 únicamente dentro de Docker;
- es publicado externamente por HAProxy como `https://homelab.casa.lan`;
- utiliza el volumen Docker externo existente `dockhand_data`.

## Estructura

```text
stack5_-_dockhand/
├── .env
├── docker-compose.yml
├── 01-prepare.sh
└── README.md
```

El `.env` solo contiene actualmente:

```text
BASE_PATH=/opt/docker
```

Se mantiene para que todos los stacks sigan el mismo contrato. Dockhand no necesita hoy variables de entorno de Compose.

## Preparación

```bash
cd /opt/docker/stack5_-_dockhand
sudo ./01-prepare.sh
```

El script valida:

- ubicación del stack respecto a `BASE_PATH`;
- existencia/driver de `redlocal`;
- existencia del volumen externo `dockhand_data`;
- sintaxis/configuración del Compose.

No crea ni modifica `dockhand_data`.

Al terminar crea `.lock`.

## Arranque

```bash
docker compose up -d
docker compose ps
docker compose logs -f dockhand
```

## Reconstrucción

```bash
rm .lock
sudo ./01-prepare.sh
```

No existe ningún directorio `service_-_dockhand` porque este despliegue persiste exclusivamente mediante el volumen Docker externo `dockhand_data`.
