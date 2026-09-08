# Stack3 — LiteLLM

LiteLLM actúa como gateway de modelos y MCP. Stack3 pasa a ser propietario de su propio servicio PostgreSQL y deja de depender de Stack2 para la infraestructura de base de datos.

Endpoints internos:

```text
http://litellm:4000
postgresql://litellm-postgres:5432/<LITELLM_DB_NAME>
```

La publicación `https://gwia.casa.lan` corresponde a HAProxy cuando Stack1 está instalado.

## Propiedad

Stack3 posee:

```text
contenedor: litellm
contenedor: litellm-postgres
runtime:    ${BASE_PATH}/service_-_litellm
runtime:    ${BASE_PATH}/service_-_litellm-postgres
```

Su única dependencia dura de otro stack es Stack0.

## Entorno

Stack3 consume el `.env` raíz mediante el enlace gestionado `./.env -> ../.env`. Las variables relevantes son:

```text
STACKS_ROOT
BASE_PATH
NETWORK_NAME
LITELLM_IMAGE
LITELLM_VERSION
LITELLM_MASTER_KEY
LITELLM_SALT_KEY
UI_USERNAME
UI_PASSWORD
STORE_MODEL_IN_DB
LITELLM_DB_NAME
LITELLM_DB_USER
LITELLM_DB_PASSWORD
```

El host y puerto PostgreSQL son detalles internos de Stack3: `litellm-postgres:5432`.

`LITELLM_SALT_KEY` debe preservarse una vez LiteLLM tenga estado cifrado en PostgreSQL.

## Lock de preparación

`.lock` significa únicamente que `01-prepare.sh` terminó correctamente. No significa que PostgreSQL o LiteLLM estén arrancados o healthy.

## Instalación nueva

```bash
cd /opt/docker/stacks/stack3_-_litellm
sudo ./01-prepare.sh
sudo ./02-postgres.sh
docker compose up -d litellm
docker compose ps
```

`02-postgres.sh` arranca y valida el PostgreSQL propiedad de Stack3. En un directorio de datos nuevo, la imagen oficial de PostgreSQL inicializa la base e identidad configuradas para LiteLLM.

## Migración desde el antiguo PostgreSQL de Stack2

Los despliegues existentes anteriores a la atomicidad de Stack3 conservan el estado de LiteLLM dentro de `firecrawl-postgres`. Para ellos existe un helper de migración de una sola vez:

```bash
sudo ./90-migrate-postgres-from-stack2.sh
```

El helper:

1. verifica que el LiteLLM actualmente desplegado sigue apuntando a `firecrawl-postgres`;
2. arranca el PostgreSQL destino vacío de Stack3;
3. detiene LiteLLM para congelar escrituras;
4. genera un `pg_dump` en formato custom bajo `/root/litellm-postgres-migration-*`;
5. restaura en `litellm-postgres`;
6. compara el inventario de tablas de usuario;
7. recrea LiteLLM contra la nueva base y espera a que alcance `healthy`;
8. conserva intacta la antigua base LiteLLM dentro de `firecrawl-postgres` como rollback.

Si se produce un fallo después de detener LiteLLM, el helper intenta recrear LiteLLM automáticamente contra la base legacy de Stack2.

La base antigua no debe eliminarse hasta validar operativamente el nuevo servicio y cerrar de forma deliberada la ventana de rollback.
