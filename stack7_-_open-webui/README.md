# Stack7 — Open WebUI

Curated chat UI over LiteLLM, with optional local web search/extraction from Stack2.

```mermaid
flowchart LR
    User --> OpenWebUI
    OpenWebUI --> LiteLLM[Stack3 LiteLLM]
    OpenWebUI -. web.search .-> SearXNG[Stack2 SearXNG]
    OpenWebUI -. web.extract .-> Firecrawl[Stack2 Firecrawl]
    HAProxy[Stack1 HAProxy] -. ingress .-> OpenWebUI
```

**Requires:** Stack0 + Stack3.  
**Optional:** Stack1 ingress, Stack2 web capabilities.  
**Default model:** `basic_autorouter`.  
**User policy:** Arena disabled; `basic_autorouter` receives explicit public-read access; global bypass remains disabled.  
**Web default:** new chats start with web search enabled, but users may turn it off.

`/app/backend/data` is persistent sensitive state and is archived by DR; `OPENWEBUI_SECRET_KEY` is persistent identity in protected configuration. The first Stack7-aware global backup and isolated restore are qualified in [../docs/dr/status.md](../docs/dr/status.md).

Stack7 policy reconciliation is part of the supported `local-ai` lifecycle. Before the first real administrator exists it is intentionally deferred without failing initial deployment. After the administrator account has been created, converge and verify the policy through the public management boundary:

```bash
./local-ai install 7 --reconcile --yes
```

The lifecycle then ensures that `basic_autorouter` is active, enables `web_search` by default and grants explicit public read access. The stack-owned Python reconciliation and verification scripts are implementation details and should not be invoked directly by operators.
