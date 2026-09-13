# Stack6 — Hermes

[Documentation TOC](../docs/TOC.md) · [Stack map](../docs/stacks/README.md) · [OpenSpec contract](../docs/devel-docs/openspec/stacks/stack6.feature)

Stack6 is the agent runtime. It combines Hermes with isolated command execution, local-first AI access through Stack3, optional Stack2 web capabilities and portable Git-backed user memory.

```mermaid
flowchart LR
    User[User] --> Hermes[Stack6 Hermes]
    Hermes --> LiteLLM[Stack3 LiteLLM]
    Hermes --> Sandbox[Isolated sandbox]
    Hermes -. optional web.search / web.extract .-> Web[Stack2]
    Memory[MEMORY.md + USER.md] <--> Sync[Memory sync]
    Sync -. optional git.remote .-> Git[Configured Git remote / Stack4]
    Cleaner[Sandbox cleanup sidecar] --> Sandbox
```

## Contract

- **Requires:** Stack0 and Stack3.
- **Optional:** Stack2 `web.search` / `web.extract`; configured Git remote, commonly Stack4.
- **Owns:** Hermes runtime, sandbox execution surface and Stack6 maintenance sidecars.
- **DR:** runtime and sandbox are reconstructable. Durable user memory is the Git-backed `MEMORY.md` + `USER.md` contract and is verified as an external prerequisite rather than copied as arbitrary container state.

Stack2 is deliberately optional. If its provider capabilities are absent or not READY, Hermes web tools remain disabled. Reconciliation enables them only after the provider is proven ready.

## Isolation boundary

Hermes does **not** receive the Docker socket. The sandbox is a deliberately narrower execution boundary and maintenance sidecars operate only on Stack6-owned runtime. This prevents an AI agent from implicitly becoming a Docker/platform administrator.

The model/provider boundary is also externalized: Hermes talks to Stack3 through dedicated least-privilege gateway credentials instead of carrying provider master credentials itself.

## Memory contract

Portable durable memory consists of the user-owned Git-backed files `MEMORY.md` and `USER.md`. Generated sandbox state, transient sessions and reconstructable runtime are not promoted to DR artifacts merely because they exist on disk.

Memory synchronization may use Stack4 Gitea when configured, but Stack6 does not require Stack4. The capability is optional so Hermes remains independently deployable.

## Lifecycle

Stack6 uses the common PREPARE → DEPLOY → READY → RECONCILE → VERIFY lifecycle. Capability reconciliation can require a restart; after any restart, readiness must be re-established before verification succeeds.

`.lock` means **PREPARED only**. It says nothing about Hermes health, sandbox readiness or optional capability convergence.

## Related decisions

- [SDR-0002 — agent runtime without Docker socket](../docs/devel-docs/sdr/0002-agent-runtime-without-docker-socket.md)
- [SDR-0003 — least-privilege AI gateway credentials](../docs/devel-docs/sdr/0003-least-privilege-ai-gateway-credentials.md)
- [SDR-0004 — internal-only service networking](../docs/devel-docs/sdr/0004-internal-only-service-networking.md)
- [Hermes operator integration](../docs/user-docs/integrations/hermes.md)
- [Stack6 DR verifier/status](../docs/dr/status.md)

Key implementation files: `docker-compose.yml`, `config/hermes/config.yaml`, sandbox/maintenance configuration, `manifest.json`, and stack lifecycle scripts.
