# SDR-0003 — Least-privilege AI gateway credentials

Status: accepted

## Risk

Reusing the LiteLLM administrative/master credential in applications turns compromise of any UI or agent into gateway administration compromise.

## Decision

Applications receive dedicated LiteLLM virtual keys scoped to their required model access. Open WebUI and Hermes do not reuse the LiteLLM administrative master key and do not share one application credential with each other.

## Verification

- Stack7 bootstrap issues a dedicated key.
- Secrets remain in protected operational configuration.
- Application documentation must never instruct operators to substitute the master key as a shortcut.
