# Stack2 — SearXNG + Firecrawl

[Home](../README.md) · [Install](../INSTALLATION.md) · [DR](../bkp-dr/README.md) · [Secrets](../.env.secretsexplained.md)

Stack2 provides local `web.search` and `web.extract`. It requires Stack0 and is an optional capability provider for Stack6.

```mermaid
flowchart LR
  S0[Stack0] --> S2[Stack2]
  S2 -. web.search/web.extract .-> S6[Stack6 Hermes]
  FC[Firecrawl] --> PG[(PostgreSQL database postgres)]
  FC --> R[Redis/RabbitMQ]
  S2 --> SX[SearXNG]
```

PostgreSQL uses `postgres` only for bootstrap/ownership/pg_cron and dedicated non-admin role `firecrawl` for application connectivity. Admin password is a restricted runtime secret; `FIRECRAWL_DB_PASSWORD` is the application credential. Existing PGDATA must be preserved during normal maintenance.

Readiness must prove both SearXNG and Firecrawl usable before optional consumers are reconciled. DR classification: **reconstructable**; Firecrawl PostgreSQL, Redis, RabbitMQ and SearXNG state are intentionally not full-rebuild backup targets.

Executable truth: [`manifest.json`](manifest.json), Compose file and lifecycle/readiness scripts in this directory.
