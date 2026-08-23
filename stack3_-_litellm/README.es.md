# Stack3 — LiteLLM

LiteLLM actúa como gateway de IA y utiliza el PostgreSQL ya desplegado por Stack2. La infraestructura PostgreSQL es compartida, pero LiteLLM tiene usuario, contraseña y base de datos propios.

LiteLLM no termina TLS. Su endpoint interno es:

```text
http://litellm:4000
```

La publicación `https://gwia.casa.lan` corresponde a HAProxy.

## Estructura

```text
stack3_-_litellm/
├── .env
├── docker-compose.yml
├── 01-prepare.sh
├── 02-postgres.sh
├── README.md
└── config/
    └── litellm/
        └── config.yaml
```

Ruta operativa:

```text
${BASE_PATH}/service_-_litellm/config/config.yaml
```

## `.env`

Variables actuales:

```text
BASE_PATH
LITELLM_MASTER_KEY
LITELLM_SALT_KEY
UI_USERNAME
UI_PASSWORD
STORE_MODEL_IN_DB
POSTGRES_HOST
POSTGRES_PORT
LITELLM_DB_NAME
LITELLM_DB_USER
LITELLM_DB_PASSWORD
```

Se han eliminado `STACK2_ENV_STATE` y `LITELLM_PORT`, porque pertenecían al proceso de instalación antiguo y no son necesarios en el Compose actual.

Todos los secretos deben existir antes de ejecutar `01-prepare.sh`. En especial, `LITELLM_SALT_KEY` debe conservarse de forma estable una vez LiteLLM tenga datos cifrados en PostgreSQL.

## Nuevo proceso de instalación

### 1. Stack2 debe estar operativo

Debe existir y estar arrancado `firecrawl-postgres`.

### 2. Preparar LiteLLM

```bash
cd /opt/docker/stack3_-_litellm
sudo ./01-prepare.sh
```

Este paso valida `.env`, migra la antigua `/opt/docker/litellm` si procede, crea `redlocal` si falta y sustituye la configuración operativa de LiteLLM.

No crea `.lock`, porque falta todavía el provisionado PostgreSQL.

### 3. Provisionar PostgreSQL

```bash
sudo ./02-postgres.sh
```

`02-postgres.sh` lee directamente, solo durante el provisionado:

```text
${BASE_PATH}/stack2_-_searxng_firecrawl/.env
```

De ahí obtiene únicamente:

```text
POSTGRES_USER
POSTGRES_PASSWORD
POSTGRES_DB
```

Esas credenciales **no se copian ni se escriben** en el `.env` de Stack3. El script crea o actualiza el rol de LiteLLM, crea su base si falta, asegura el propietario y comprueba una conexión usando las credenciales definitivas de LiteLLM.

Al terminar correctamente crea `.lock`.

### 4. Arrancar LiteLLM

```bash
docker compose up -d
docker compose ps
docker compose logs -f litellm
```

## Reconstrucción deliberada

```bash
rm .lock
sudo ./01-prepare.sh
sudo ./02-postgres.sh
```

`02-postgres.sh` es seguro respecto a la persistencia: crea/actualiza la identidad PostgreSQL de LiteLLM, pero no elimina la base de datos ni sus tablas.
