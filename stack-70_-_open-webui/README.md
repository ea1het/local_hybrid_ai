<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Stack 70 — Open WebUI

[Reading guide](../README.md#reading-guide) · [Operations](../docs/operations.md) · Next: [Stack 60 · Hermes](../stack-60_-_hermes/README.md)

The chat interface. It uses LiteLLM for models and, when available, Stack 20 for web search and page loading.

```mermaid
flowchart TB
    User -->|HTTPS via Stack 10| WebUI["open-webui"]
    WebUI --> LiteLLM["Stack 30 LiteLLM"]
    WebUI -.->|optional| Web["Stack 20 · search and page loader"]
    WebUI --> DB[("webui.db")]
```

| | |
| --- | --- |
| Install requires | Stacks 00 and 30 prepared, **`litellm` running**, and a dedicated `OPENWEBUI_LITELLM_API_KEY` placed in `.env` after configuring or restoring LiteLLM |
| Containers | `open-webui` (Compose project `Stack7 - Open WebUI`) |
| Published at | `chat.casa.lan` through Stack 10 |
| Runtime data | `${BASE_PATH}/service_-_open-webui/data` (**back up**: users, chats, settings); `OPENWEBUI_SECRET_KEY` in `.env` |
| `status` | Container `/health` (not a test of the LiteLLM key or the models) |

## Lifecycle specifics

- **`install`** runs `00-bootstrap.py` first. It fills only missing Open WebUI values in `.env` (for example the signing key), after a private backup. It never creates LiteLLM keys.
- **`start`** keeps the saved LiteLLM key in sync. Open WebUI stores its connection key in `webui.db`, and that stored key overrides Compose. If it differs from `.env`, `start` stops the container, backs up `webui.db`, replaces only that key, and starts again. An unknown database layout stops the start instead of resetting settings.
- **`reconfig`** previews LiteLLM connection drift without changes. `reconfig --apply` never stops or starts containers: with Open WebUI stopped, it backs up `webui.db` and synchronizes a changed LiteLLM key from `.env`. If a running instance has a stale key, stop it manually, run `reconfig --apply`, then start it manually.

Compose disables Arena models and enables web search. Choose the default model in Open WebUI; Stack 70 does not create or select a LiteLLM router. `wait-ready.py` waits for the container to become healthy after `start`.

Files: `docker-compose.yml`, `00-bootstrap.py`, `01-prepare.py`, `wait-ready.py`.
