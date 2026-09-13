# SDR-0004 — Internal-only service networking

Status: accepted

## Risk

Publishing databases, search engines, scraping services or application backends directly on host ports expands the attack surface and bypasses the intended ingress/security controls.

## Decision

Internal platform communication uses the Stack0-owned external Docker bridge `redlocal`. Services are not given host ports unless host exposure is an explicit part of their contract. User-facing HTTP ingress is owned by Stack1/HAProxy.

## Consequence

Inter-service URLs use Docker DNS names such as `litellm`, `searxng`, `firecrawl-api` and `open-webui`, not host-loopback workarounds.
