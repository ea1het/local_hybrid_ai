# Stack1 — HAProxy + Web

Entry stack for the `casa.lan` environment. HAProxy is the only TLS termination point. Backends speak HTTP inside the external Docker network `redlocal`.

## Services

- `haproxy`: publishes host ports 80/443 and routes to internal services.
- `web`: main static portal at `https://casa.lan`.

## Structure

```
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

### Operational paths

```
${BASE_PATH}/service_-_haproxy/config
${BASE_PATH}/service_-_web
```

The script automatically migrates the old `/opt/docker/haproxy` and `/opt/docker/web` paths if the new destination does not yet exist.

## `.env`

Must exist before running the script. Current variables:

```
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

`GWIA` and `HOMELAB` continue to be defined via `presetenv` in the current `haproxy.cfg`. No variables have been added that Compose does not consume.

## Initial preparation

Place the stack at:

```
/opt/docker/stack1_-_haproxy_web
```

Ensure `.env`, the certificate and the private key are the final/operative ones. Then:

```bash
cd /opt/docker/stack1_-_haproxy_web
sudo ./01-prepare.sh
```

The script:

1. exits without doing anything if `.lock` exists;
2. validates `.env`;
3. migrates old paths where appropriate;
4. creates/validates `redlocal`;
5. fully rewrites HAProxy's operational configuration from `config/haproxy`;
6. rewrites the web portal from `config/web`;
7. validates `haproxy.cfg` using the `haproxy:3.0-alpine` image;
8. validates the Compose file;
9. creates `.lock`.

## Start and normal operation

```bash
docker compose up -d
docker compose ps
docker compose logs -f haproxy
```

For later changes to the source files, delete `.lock` first and re-run `01-prepare.sh`. That replaces the operational configuration.

## Security

`casa.lan.key` is a private key. It must not be published in Git. Any copy intended for the repository should be sanitized or contain a non-operational example key.

### Note about the source material for this refactor

The `casa.lan.key` received in the source archive was empty. The structure retains the key as the expected location, but `01-prepare.sh` requires the file to contain data before performing any migration or rewrite. The real private key corresponding to the operative certificate must be restored there.
