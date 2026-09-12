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
