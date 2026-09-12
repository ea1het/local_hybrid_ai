# Stack7 — Open WebUI

Atomic Open WebUI chat frontend for the Local Hybrid AI platform.

## Contract

- Requires Stack0 and Stack3.
- Optionally exposed by Stack1 at `https://chat.casa.lan`.
- Optionally consumes Stack2 capabilities `web.search` and `web.extract`.
- Consumes `ai.gateway` from LiteLLM using the OpenAI-compatible API.
- Provides `ai.chat-ui`.
- Owns only `open-webui` and `${BASE_PATH}/service_-_open-webui`.
- Publishes no host port; HAProxy reaches `open-webui:8080` through `redlocal`.

The image is pinned by `OPENWEBUI_IMAGE` + `OPENWEBUI_VERSION`. `main`, `dev` and `latest` are deliberately rejected by preparation.

## Explicit bootstrap

PREPARE never writes the protected central `.env`. On a host that does not yet have Stack7 values, run the explicit operator bootstrap once **after Stack3/LiteLLM is healthy**:

```bash
python3 stack7_-_open-webui/00-bootstrap-env.py
```

The utility:

- preserves any already-valid Stack7 values;
- adds only missing/placeholder Stack7 variables;
- generates `OPENWEBUI_SECRET_KEY` locally with cryptographic randomness;
- asks the running LiteLLM instance to issue a dedicated virtual key scoped to the model ids visible at bootstrap time;
- verifies that the generated key can list models;
- atomically rewrites the existing root `.env` as `root:root 0600`;
- never prints the generated secrets.

It is intentionally **not** part of `installer/lifecycle.json`: secret issuance and mutation of the global operational environment are explicit operator actions, not PREPARE side effects.

## Model policy bootstrap

For a fresh Open WebUI database, Compose seeds these instance defaults:

```text
DEFAULT_MODELS=basic_autorouter
ENABLE_EVALUATION_ARENA_MODELS=false
```

Persistent ConfigVar values remain enabled; Stack7 deliberately does **not** set `ENABLE_PERSISTENT_CONFIG=false`. Therefore later deliberate administrative changes remain persistent and, on an already initialized database, persisted values take precedence over newly-added environment defaults.

After the first Open WebUI administrator account exists, run:

```bash
python3 stack7_-_open-webui/03-reconcile-model-policy.py
```

The reconciler is idempotent and Stack7-owned. It executes inside the pinned Open WebUI container and uses Open WebUI's ORM/data layer rather than editing SQLite directly. It ensures `basic_autorouter` is active, preserves existing model metadata while enabling the declared capabilities, sets `web_search` as a default feature, and adds the Open WebUI public-read access grant (`user:*:read`). It does not touch LiteLLM and does not enable `BYPASS_MODEL_ACCESS_CONTROL`.

The first-admin dependency is intentional: Open WebUI model records have an owner. Stack7 does not manufacture an administrator identity or introduce a bootstrap admin password solely to satisfy this policy step.

## Secrets

Stack7 uses two independent persistent secrets from the protected central `.env`:

- `OPENWEBUI_SECRET_KEY`: Open WebUI cryptographic/session identity. Never rotate implicitly after persistent state exists.
- `OPENWEBUI_LITELLM_API_KEY`: dedicated least-privilege LiteLLM inference credential for Open WebUI. Do not reuse the LiteLLM administrative master key or the Hermes key.

Open WebUI persists provider and web-tool configuration in its internal database after first launch. Many web-related settings are Open WebUI `ConfigVar` values: on an existing instance, the persisted database value takes precedence over a newly-added Compose environment variable. For an already-initialized deployment, use the Admin UI for the one-time change unless the whole instance is deliberately managed with `ENABLE_PERSISTENT_CONFIG=false`.

## Web search and page extraction

Stack7 does not run its own search or scraping containers. It consumes the services owned by Stack2 over `redlocal`:

- web search: SearXNG at `http://searxng:8080`;
- page loading/extraction: Firecrawl at `http://firecrawl-api:3002`.

Compose configures the Open WebUI defaults with:

```text
ENABLE_WEB_SEARCH=true
WEB_SEARCH_ENGINE=searxng
SEARXNG_QUERY_URL=http://searxng:8080/search?q=<query>
WEB_SEARCH_RESULT_COUNT=5
WEB_SEARCH_CONCURRENT_REQUESTS=10
WEB_LOADER_ENGINE=firecrawl
FIRECRAWL_API_BASE_URL=http://firecrawl-api:3002
FIRECRAWL_TIMEOUT=30000
```

The current self-hosted Firecrawl deployment has authentication disabled, therefore `FIRECRAWL_API_KEY` is intentionally empty. SearXNG JSON output is enabled by Stack2's managed `settings.yml`, which is required by Open WebUI's SearXNG integration.

Stack2 remains optional to Stack7: chat/inference through LiteLLM continues to work if Stack2 is unavailable, while web search/extraction is degraded until those optional capabilities return.

## Persistence and DR

`/app/backend/data` is bind-mounted from `${BASE_PATH}/service_-_open-webui/data` and contains Open WebUI users, chats, settings and application data.

The recovery contract treats this state as sensitive persistent data. `backup all` quiesces the `open-webui` container before archiving the data directory and restarts it afterwards so the SQLite-backed state is captured consistently. `OPENWEBUI_SECRET_KEY` is declared separately as persistent identity and is also present in the globally protected operational `.env` backup.

## Lifecycle

The common installer owns the lifecycle:

```text
PREPARE -> DEPLOY -> READY -> VERIFY
```

Readiness requires the Open WebUI container healthcheck to become healthy. Stack7 does not introduce any Open-WebUI-specific branch in `install.py`.
