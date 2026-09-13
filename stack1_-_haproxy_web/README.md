# Stack1 — HAProxy + Web

[Documentation TOC](../docs/TOC.md) · [Stack map](../docs/stacks/README.md) · [OpenSpec contract](../docs/devel-docs/openspec/stacks/stack1.feature)

Stack1 owns the platform HTTP/HTTPS ingress and the small static landing page. Application backends remain owned by their own stacks; Stack1 only publishes selected services.

```mermaid
flowchart LR
    Client[Client] -->|HTTP / HTTPS| HAProxy[Stack1 HAProxy]
    HAProxy --> Static[Stack1 static web]
    HAProxy -. optional routes .-> Apps[Application stacks on redlocal]
    PKI[Stack0 PKI] -->|read-only mount| HAProxy
    Network[Stack0 redlocal] --- HAProxy
```

## Contract

- **Requires:** Stack0.
- **Provides:** ingress/web publication capability.
- **Owns:** `haproxy` and `web` containers plus their Stack1 runtime directories.
- **DR:** reconstructable; Stack1 has no durable recovery artifact.
- **Security boundary:** application backends should normally remain internal to `redlocal` instead of publishing host ports directly.

Stack0 owns both `redlocal` and the platform PKI. Stack1 consumes those resources but never owns or regenerates them. HAProxy mounts the Stack0 PKI read-only; certificate lifecycle remains a Stack0 responsibility.

## Runtime behaviour

HAProxy is deliberately tolerant of optional backends. A backend that is absent or temporarily unavailable must not prevent Stack1 itself from starting. This allows stacks to remain independently deployable while sharing one ingress layer.

Updating a file on disk does not necessarily reload the HAProxy process. Configuration, mount, group or certificate changes require controlled lifecycle convergence through `./local-ai`; direct Compose operations are implementation details, not the supported operator contract.

`.lock` means **PREPARED only**. It does not mean HAProxy is running, healthy or serving every optional backend.

## Security invariants

- TLS private keys remain owned by Stack0 PKI and are not copied into Stack1.
- Backend services stay on `redlocal` unless an explicit architecture decision publishes them.
- Stack1 does not become owner of application state merely because it exposes an application route.
- The supported operator boundary is `./local-ai`; stack scripts and Compose files remain private implementation surfaces.

## Related decisions

- [ADR-0002 — single management CLI](../docs/devel-docs/adr/0002-single-management-cli.md)
- [SDR-0004 — internal-only service networking](../docs/devel-docs/sdr/0004-internal-only-service-networking.md)
- [Configuration and secrets](../docs/configuration/env-secrets.md)

Key implementation files: `docker-compose.yml`, `config/haproxy/haproxy.cfg`, `manifest.json`, and the stack-owned lifecycle scripts.
