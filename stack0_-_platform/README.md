# Stack0 — Platform foundation

Stack0 owns host-level resources shared by every deployable stack. It is not an application stack and does not run its own Docker Compose services.

## Responsibilities

Stack0 owns:

- validation of the root operational `.env`;
- compatibility symlinks `stackN/.env -> ../.env`;
- the shared Docker network declared by `NETWORK_NAME`;
- persistent platform runtime below `${BASE_PATH}/service_-_platform`;
- centralized TLS/PKI lifecycle;
- the manifest registry and dependency graph for every stack.

Stack0 does **not** own application databases, application volumes, Gitea repositories, LiteLLM dynamic objects or Hermes-specific SSH identities.

## Runtime layout

```text
${BASE_PATH}/service_-_platform/
├── pki/
│   ├── tls.crt
│   └── tls.key
├── state/
└── logs/
```

Stack0 creates the dedicated `local-hybrid-pki` group with `PLATFORM_PKI_GID` (default `1999`). The PKI directory is `root:<PKI GID> 0750`, the certificate `0644` and the private key `0640`. HAProxy consumes the directory read-only with that supplementary group. Existing group/GID conflicts stop preparation.

The current PKI is self-signed and covers both `ROOT_HOSTNAME` and `*.ROOT_HOSTNAME`.

## Preparation

```bash
cd /opt/docker/stacks/stack0_-_platform
sudo ./install.sh
```

Preparation is idempotent. Existing valid PKI material is preserved and is never rotated implicitly.

`.lock` means only that Stack0 preparation completed successfully.

## PKI lifecycle

```bash
sudo ./pki.sh status
sudo ./pki.sh create
sudo ./pki.sh renew
sudo ./pki.sh recreate --yes
sudo ./pki.sh delete --yes
```

`renew` preserves the private key. `recreate` replaces both certificate and key and therefore requires explicit confirmation.

## Manifest registry

Every stack directory contains `manifest.json`. Stack0 discovers those manifests instead of hard-coding a dependency table.

Useful commands:

```bash
python3 manifests.py validate
python3 manifests.py validate --target
python3 manifests.py list
python3 manifests.py plan 6
python3 manifests.py plan 6 --target
python3 manifests.py plan all
```

The registry deliberately distinguishes the **current** dependency graph from the **target atomic** graph while refactoring is in progress.

Stack3 owns its dedicated PostgreSQL and requires only Stack0. Stack6 currently still requires Stack2 because its preparation flow hard-requires local web services; its target graph requires only Stack0 and Stack3.

This makes the remaining atomicity blockers explicit and machine-readable instead of hiding them inside installation scripts.

## Dependency model

Target architecture:

```text
Stack0 -> Stack1
       -> Stack2
       -> Stack3
       -> Stack4
       -> Stack5
       -> Stack6

Stack6 additionally requires Stack3.
```

Stack2 and Stack4 are optional capability providers for Stack6 in the target model.
