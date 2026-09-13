# User documentation

This area contains the supported operator-facing contract for Local Hybrid AI. Operators and external automation use `./local-ai`; implementation files under `commands/`, `internal/`, `installer/`, `bkp-dr/` and the stack directories are not public management APIs.

Start with:

- [CLI reference](cli.md) for the complete supported management surface.
- [Installation](../installation.md) for planning, installation and lifecycle convergence.
- [Upgrade policy](../upgrade-policy.md) for registry discovery, compatibility policy, explicit selection and guarded execution.
- [Disaster recovery](../dr/howto.md) for backup, restore planning, isolated drills and clean-target recovery.
- [Configuration and secrets](../configuration/env-secrets.md) for the protected root environment and secret ownership.
- [LiteLLM MCP gateway](integrations/litellm-mcp.md) and [Hermes integrations](integrations/hermes.md) for operator-managed integrations.

The documentation describes the behavior implemented by the current `main` branch. Where a command is intentionally not available as stable JSON, the CLI fails explicitly rather than pretending a machine contract exists.
