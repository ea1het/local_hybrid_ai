# Stack1 — HAProxy + Web

Stack de entrada de `casa.lan`. HAProxy termina TLS y comunica con los backends por HTTP sobre la red compartida de Stack0.

## Servicios y propiedad

- `haproxy`: publica HTTP/HTTPS y enruta a los servicios internos.
- `web`: sirve el portal estático de `https://casa.lan`.

Stack1 requiere únicamente Stack0. Los demás stacks son backends opcionales: `init-addr last,none` permite arrancar HAProxy aunque no estén disponibles.

Stack0 posee la red y la PKI:

```text
${BASE_PATH}/service_-_platform/pki/tls.crt
${BASE_PATH}/service_-_platform/pki/tls.key
```

Stack1 posee:

```text
${BASE_PATH}/service_-_haproxy/config
${BASE_PATH}/service_-_web
```

Stack1 no genera ni copia material TLS. Monta el directorio PKI de Stack0 en `/etc/platform-pki` como solo lectura. Los enlaces `casa.lan.crt` y `casa.lan.key` de su configuración apuntan a ese montaje dentro del contenedor.

## Fuentes

```text
stack1_-_haproxy_web/
├── docker-compose.yml
├── 01-prepare.sh
├── manifest.json
└── config/
    ├── haproxy/haproxy.cfg
    └── web/index.html
```

La generación de certificados pertenece a `stack0_-_platform/pki.sh`. Los certificados locales heredados que puedan quedar en source están ignorados por Git y no son entradas de la preparación actual.

## Entorno y permisos

El enlace `.env -> ../.env` permite consumir el contrato central:

```text
STACKS_ROOT
BASE_PATH
NETWORK_NAME
PLATFORM_PKI_GID
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
GWIA_HOSTNAME
GWIA_TARGET
HOMELAB_HOSTNAME
HOMELAB_TARGET
AGENTIA_HOSTNAME
AGENTIA_TARGET
```

`PLATFORM_PKI_GID` vale `1999` por defecto. Stack0 crea el grupo `local-hybrid-pki` y mantiene la clave privada con propietario root y permisos `0640`. Tanto la validación como el servicio HAProxy reciben ese grupo suplementario.

## Preparación y arranque

Preparar primero Stack0:

```bash
cd /opt/docker/stacks
sudo ./stack0_-_platform/install.sh
```

Después:

```bash
cd /opt/docker/stacks/stack1_-_haproxy_web
sudo ./01-prepare.sh
docker compose up -d
docker compose ps
```

La preparación verifica la red existente y la pareja certificado/clave, actualiza la configuración y los enlaces TLS, instala el contenido web y valida HAProxy y Compose. Solo entonces crea `.lock`.

`.lock` significa únicamente PREPARED. Si existe, el script sale sin modificar nada.

## Repetir la preparación

```bash
rm .lock
sudo ./01-prepare.sh
```

La preparación conserva los directorios montados de HAProxy y web para que los contenedores en ejecución sigan viendo su contenido. Actualiza los archivos fuente y los enlaces TLS sin eliminar esos directorios. Conserva otros archivos existentes; retirar archivos obsoletos requiere una operación deliberada aparte.

Actualizar archivos no recarga la configuración del proceso HAProxy. Cuando corresponda, aplicar una recarga o recreación controlada. Los cambios de mounts o grupos de Compose requieren recrear el contenedor. Las actualizaciones del contenido estático no requieren recrear `web`.

## Ciclo de vida de PKI

Pertenece exclusivamente a Stack0:

```bash
sudo ../stack0_-_platform/pki.sh status
sudo ../stack0_-_platform/pki.sh renew
sudo ../stack0_-_platform/pki.sh recreate --yes
```

Montar el directorio completo permite ver archivos sustituidos en la PKI. HAProxy necesita una recarga o recreación controlada para servir un certificado renovado. Durante la adopción inicial, conservar el certificado existente y comprobar su fingerprint antes y después.

Nunca publicar claves privadas en Git ni copiarlas al runtime de Stack1.
