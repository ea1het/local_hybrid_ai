# Stack7 — Open WebUI

Atomic Open WebUI chat frontend for the Local Hybrid AI platform.

## Contract

- Requires Stack0 and Stack3.
- Optionally exposed by Stack1 at `https://chat.casa.lan`.
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

## Secrets

Stack7 uses two independent persistent secrets from the protected central `.env`:

- `OPENWEBUI_SECRET_KEY`: Open WebUI cryptographic/session identity. Never rotate implicitly after persistent state exists.
- `OPENWEBUI_LITELLM_API_KEY`: dedicated least-privilege LiteLLM inference credential for Open WebUI. Do not reuse the LiteLLM administrative master key or the Hermes key.

Open WebUI persists provider connection configuration in its internal database after first launch. Changing only the environment later may not overwrite persisted connection settings; use the Open WebUI admin interface for intentional post-bootstrap connection changes.

## Persistence and DR

`/app/backend/data` is bind-mounted from `${BASE_PATH}/service_-_open-webui/data` and contains Open WebUI users, chats, settings and application data.

The recovery contract treats this state as sensitive persistent data. `backup all` quiesces the `open-webui` container before archiving the data directory and restarts it afterwards so the SQLite-backed state is captured consistently. `OPENWEBUI_SECRET_KEY` is declared separately as persistent identity and is also present in the globally protected operational `.env` backup.

## Lifecycle

The common installer owns the lifecycle:

```text
PREPARE -> DEPLOY -> READY -> VERIFY
```

Readiness requires the Open WebUI container healthcheck to become healthy. Stack7 does not introduce any Open-WebUI-specific branch in `install.py`.
