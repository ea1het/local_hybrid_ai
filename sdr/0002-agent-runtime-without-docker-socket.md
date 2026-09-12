# SDR-0002 — Agent runtime without Docker socket

Status: accepted

## Risk

Giving an AI agent direct Docker-socket access is effectively host-level control and collapses the isolation boundary between model/tool execution and the platform.

## Decision

Hermes does not receive the Docker socket. Command execution is isolated in the dedicated sandbox path/container and optional local capabilities fail closed when their prerequisite is unavailable.

## Consequence

Some operations require explicit host-side lifecycle tooling instead of being delegated to the agent. This is intentional privilege separation.

## Verification

- Stack6 Compose must not mount `/var/run/docker.sock` into Hermes.
- Stack6 lifecycle tests and manifest ownership remain the enforcement points.
