# Stack1 — HAProxy + Web

Entry stack for the `casa.lan` environment. HAProxy is the only TLS termination point. Backends speak HTTP inside the shared Docker network from Stack0.

## Services

- `haproxy`: publishes host ports 80/443 and routes to internal services.
- `web`: main static portal at `https://casa.lan`.

## Dependency and ownership contract

Stack1 is atomic and requires only Stack0.

Stack0 owns:

```text
${BASE_PATH}/service_-_platform/pki/tls.crt
${BASE_PATH}/service_-_platform/pki/tls.key
shared Docker network
```

Stack1 owns:

```text
${BASE_PATH}/service_-_haproxy/config
${BASE_PATH}/service_-_web
```

Stack1 never generates or copies TLS private material. Its HAProxy runtime config contains compatibility symlinks that resolve inside the container to the read-only Stack0 PKI mount.

## Structure

```text
stack1_-_haproxy_web/
├── .env
├── docker-compose.yml
├── 01-prepare.sh
├── README.md
└── config/
    ├── haproxy/
    │   └── haproxy.cfg
    └── web/
        └── index.html
```

Certificate-generation files no longer belong to Stack1. PKI lifecycle is centralized in `stack0_-_platform/pki.sh`.

## Environment

Stack1 consumes the central deployment environment through `.env -> ../.env`, including:

```text
STACKS_ROOT
BASE_PATH
NETWORK_NAME
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

The backend stacks are optional from Stack1's installation perspective. HAProxy uses Docker DNS with `init-addr last,none`, so a backend may be absent when Stack1 starts.

## Preparation

Stack0 must already be prepared, including its network and PKI:

```bash
cd /opt/docker/stacks
sudo ./stack0_-_platform/install.sh
```

Then:

```bash
cd /opt/docker/stacks/stack1_-_haproxy_web
sudo ./01-prepare.sh
```

`01-prepare.sh`:

1. validates the central environment contract used by Stack1;
2. verifies the shared Docker network from Stack0 without creating it;
3. validates the Stack0 certificate/private-key pair;
4. deploys only `haproxy.cfg` into Stack1 runtime;
5. creates runtime symlinks for HAProxy's historical certificate filenames, pointing to the Stack0 PKI mount;
6. deploys the static web content;
7. validates HAProxy using the same central PKI mount used at runtime;
8. validates Compose;
9. creates `.lock`.

`.lock` means only PREPARED.

## Start and normal operation

```bash
docker compose up -d
docker compose ps
docker compose logs -f haproxy
```

## PKI lifecycle

Certificate lifecycle belongs exclusively to Stack0:

```bash
sudo ../stack0_-_platform/pki.sh status
sudo ../stack0_-_platform/pki.sh renew
sudo ../stack0_-_platform/pki.sh recreate --yes
```

Stack1 mounts the whole PKI directory read-only, rather than individual files. This ensures replacement files remain visible inside the container. HAProxy still needs a controlled reload/recreate after certificate renewal or recreation before it begins serving the new certificate.

Stack1 must never store the TLS private key in Git or copy it into `service_-_haproxy`.
