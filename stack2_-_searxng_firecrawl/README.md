# Stack2 — SearXNG + Firecrawl

Stack2 is the local web search/extraction capability provider. It is atomic, requires only Stack0, and provides `web.search` and `web.extract`.

```mermaid
flowchart LR
    H[Hermes when reconciled] --> SX[SearXNG :8080]
    H --> FC[Firecrawl API :3002]
    FC --> SX
    FC --> R[Redis]
    FC --> Q[RabbitMQ]
    FC --> P[(Firecrawl PostgreSQL)]
```

No Stack2 service publishes an application port directly to the host. SearXNG can be exposed through Stack1/HAProxy; Firecrawl and its supporting services remain internal to `redlocal`.

## Ownership

Stack2 owns six containers: SearXNG, Firecrawl API, Firecrawl Playwright, Redis, RabbitMQ and Firecrawl PostgreSQL. It also owns the corresponding SearXNG and Firecrawl runtime roots declared in its manifest.

It does **not** own `redlocal`; Stack0 creates/validates the shared network.

## Persistence

```text
${BASE_PATH}/service_-_searxng/config
${BASE_PATH}/service_-_searxng/data
${BASE_PATH}/service_-_firecrawl-redis/data
${BASE_PATH}/service_-_firecrawl-rabbitmq/data
${BASE_PATH}/service_-_firecrawl-postgres/data
```

PREPARE preserves the existing SearXNG configuration directory identity and persistent data directories. It synchronizes managed configuration without replacing a live bind-mounted directory.

Firecrawl PostgreSQL belongs only to Stack2. LiteLLM no longer uses this database in the current architecture.

## Preparation, deployment and readiness

```bash
cd /opt/docker/stacks/stack2_-_searxng_firecrawl
sudo ./01-prepare.sh
docker compose up -d
sudo bash ./02-wait-ready.sh
docker compose ps
```

PREPARE requires Stack0 `.lock`, verifies the existing shared bridge network without creating it, prepares stack-owned runtime paths/configuration, validates Compose and creates `.lock` only after success.

`.lock` means PREPARED, not deployed/healthy/ready.

`docker compose up -d` establishes process state, but **DEPLOYED is not READY**. `02-wait-ready.sh` waits up to its bounded timeout until both provider endpoints accept connections:

```text
web.search  -> searxng:8080
web.extract -> firecrawl-api:3002
```

The common installer runs this readiness gate after Stack2 deployment and again during Stack2 verification. Consumer reconciliation occurs only after the deploy-time readiness gate succeeds.

This behavior was validated by stopping only SearXNG and recovering Stack2 through the common installer: the same SearXNG container was restarted rather than recreated, readiness completed before Stack6 reconciliation, Hermes remained unchanged, and a second installer run returned to verification-only convergence.

## Internal endpoints

```text
SearXNG:        http://searxng:8080
Firecrawl API: http://firecrawl-api:3002
PostgreSQL:    firecrawl-postgres:5432
Redis:         firecrawl-redis:6379
RabbitMQ:      firecrawl-rabbitmq:5672
```

## Stack6 integration

Stack6 does not require Stack2. Without a ready Stack2, Hermes web tools remain explicitly disabled.

Preferred incremental operation from repository root:

```bash
sudo python3 install.py 2 --yes
```

If Stack2 is already healthy/ready, this verifies it and does not spuriously reconcile Stack6. If Stack2 must actually deploy/recover, the common installer waits for provider readiness, discovers prepared consumers through manifest capabilities, and reconciles Stack6 automatically.

Manual equivalent after deploying/restoring Stack2:

```bash
sudo bash ./02-wait-ready.sh
cd /opt/docker/stacks/stack6_-_hermes
sudo ./06-reconcile-capabilities.sh --restart
```

Reconciliation enables web only when both provider containers are present on the configured shared network; the common installer additionally guarantees readiness before it invokes that reconciliation during a provider transition. Provider disappearance reverses the managed configuration to explicit web-disabled state when reconciled; it does not trigger an external web fallback.

```mermaid
stateDiagram-v2
    [*] --> WebDisabled
    WebDisabled --> LocalWeb: provider READY + reconcile
    LocalWeb --> WebDisabled: provider unavailable + reconcile
```

## Re-preparation

```bash
rm .lock
sudo ./01-prepare.sh
```

Use this only when PREPARE itself must be repeated. Optional-capability activation in Stack6 uses reconciliation and does not require re-preparing Stack6.
