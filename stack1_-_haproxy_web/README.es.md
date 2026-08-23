# Stack1 — HAProxy + Web

Stack de entrada del entorno `casa.lan`. HAProxy es el **único punto de terminación TLS**. Los backends hablan HTTP dentro de la red Docker externa `redlocal`.

Servicios del Compose:

- `haproxy`: publica 80/443 del host y enruta a los servicios internos.
- `web`: portal estático principal de `https://casa.lan`.

## Estructura

```text
stack1_-_haproxy_web/
├── .env
├── docker-compose.yml
├── 01-prepare.sh
├── README.md
└── config/
    ├── haproxy/
    │   ├── haproxy.cfg
    │   ├── casa.lan.crt
    │   ├── casa.lan.key
    │   ├── minimal.cnf
    │   └── generate.txt
    └── web/
        └── index.html
```

Rutas operativas:

```text
${BASE_PATH}/service_-_haproxy/config
${BASE_PATH}/service_-_web
```

El script migra automáticamente las antiguas `/opt/docker/haproxy` y `/opt/docker/web` si el nuevo destino todavía no existe.

## `.env`

Debe existir antes de ejecutar el script. Variables actuales:

```text
BASE_PATH
HAPROXY_HTTP_PORT
HAPROXY_HTTPS_PORT
ROOT_HOSTNAME
WEB_TARGET
SEARCH_HOSTNAME
SEARCH_TARGET
CHAT_HOSTNAME
CHAT_TARGET
GIT_HOSTNAME
GIT_TARGET
```

`GWIA` y `HOMELAB` continúan definidos mediante `presetenv` en el `haproxy.cfg` actual. No se han añadido variables que el Compose no consuma.

## Preparación inicial

Colocar el stack en:

```text
/opt/docker/stack1_-_haproxy_web
```

Asegurar que `.env`, el certificado y la clave privada son los definitivos. Después:

```bash
cd /opt/docker/stack1_-_haproxy_web
sudo ./01-prepare.sh
```

El script:

1. sale sin hacer nada si existe `.lock`;
2. valida `.env`;
3. migra las rutas antiguas cuando procede;
4. crea/valida `redlocal`;
5. reescribe completamente la configuración operativa de HAProxy desde `config/haproxy`;
6. reescribe el portal web desde `config/web`;
7. valida `haproxy.cfg` con la imagen `haproxy:3.0-alpine`;
8. valida el Compose;
9. crea `.lock`.

## Arranque y operación normal

```bash
docker compose up -d
docker compose ps
docker compose logs -f haproxy
```

Para cambios posteriores en los ficheros fuente, borrar primero `.lock` y volver a ejecutar `01-prepare.sh`. Esto reemplaza la configuración operativa.

## Seguridad

`casa.lan.key` es una clave privada. No debe publicarse en Git. La copia destinada al repositorio debe estar saneada o contener una clave de ejemplo no operativa.

### Nota sobre el material de origen de este refactor

El `casa.lan.key` recibido en el archivo de origen estaba vacío. La estructura lo conserva como ubicación de la clave, pero `01-prepare.sh` exige que el fichero tenga contenido antes de realizar ninguna migración o reescritura. Debe restaurarse ahí la clave privada real que corresponde al certificado operativo.
