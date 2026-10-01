<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Local Hybrid AI

Local-first AI infrastructure split into eight Docker stacks. The repository contains Python preparation modules, Compose definitions, operational wrappers, tests, and configuration examples. Installation state and secrets belong outside Git; the root `.env` is the protected operational configuration.

## Stacks and dependencies

| Stack | Purpose | Dependencies |
|---|---|---|
| [00 · Platform](stack-00_-_platform/README.md) | Shared directories and network, local CA trust, HAProxy TLS | Host Docker and operational `.env` |
| [10 · HAProxy/Web](stack-10_-_haproxy_web/README.md) | HTTPS ingress and static landing page | 00 |
| [20 · SearXNG/Firecrawl](stack-20_-_searxng_firecrawl/README.md) | Optional local search and extraction | 00 |
| [30 · LiteLLM](stack-30_-_litellm/README.md) | AI gateway and PostgreSQL | 00 |
| [40 · Gitea](stack-40_-_gitea/README.md) | Git service and Actions runner | 00; 10 for optional ingress |
| [50 · Dockhand](stack-50_-_dockhand/README.md) | Optional Docker management UI | Shared Docker bridge network; 10 for optional ingress |
| [60 · Hermes](stack-60_-_hermes/README.md) | Agent, sandbox, and maintenance sidecars | 00 and running 30; 20 and 40 optional |
| [70 · Open WebUI](stack-70_-_open-webui/README.md) | Chat UI over LiteLLM | 00 and running 30; 10 and 20 optional |

Stack 00 owns common host prerequisites. Stack 20 is an optional provider, not an automatic external-web fallback. Stack 30 is the required gateway for AI consumers. Each stack README describes its specific state and manual follow-up steps.

## Installation and operations

Run `./local-ai` from the repository root with Python 3 and Docker Compose available. It dispatches `stack-NN` to the matching `wrapper/bin/stack-NN.py` and forwards all remaining arguments and the exit status. Run `sudo ./local-ai env bootstrap` before stack installation to create or complete the protected `.env` from [`.env.template`](.env.template). It generates only local secrets, preserves existing values, and backs up an existing `.env` before changing it. PostgreSQL passwords are sourced from `.env`; no runtime password files are created or mounted. External credentials remain pending; do not commit credentials. Initial preparation and lifecycle commands need root privileges. For example:

```bash
cd /opt/docker/stacks
sudo ./local-ai stack-00 install
sudo ./local-ai stack-00 status --deep
sudo ./local-ai stack-10 install
sudo ./local-ai stack-10 start
sudo ./local-ai stack-10 status
sudo ./local-ai stack-10 stop
```

Use `./local-ai --help` to list available stacks. The current names are `stack-00`, `stack-10`, …, `stack-70`; `stack-01` is not present. Stack 00 has **`install` and `status` only**: it has no containers to start or stop. Stack 00 `install` audits and repairs missing platform prerequisites even when `.lock` exists, and writes/retains its lock only after verification. Other stacks' `install` normally stops at an existing `.lock`; removing a lock can trigger destructive reconfiguration and requires a deliberate review and backup. A lock means **prepared**, never running or healthy.

Interactive `install`, `start`, and `stop` commands display an indeterminate activity bar during long, captured subprocesses. The bar reports elapsed time, not a guessed percentage; pipes and CI receive unchanged output. Enable command, verb, and option completion in Bash with `eval "$(./local-ai completion bash)"` or in Zsh with `autoload -Uz compinit && compinit && eval "$(./local-ai completion zsh)"`. Completion covers `--deep` for `status`; use `./local-ai <stack> <verb> --help` for option descriptions.

For Stacks 10–70, `install` does not leave application services running. Stack 30 additionally provisions PostgreSQL and issues minimal Hermes/Open WebUI keys in a disposable LiteLLM container; Stack 40 initializes its administrator in disposable Gitea containers. `start` runs Compose `up -d` (`--build` for 60); `stop` runs Compose `down` without `--volumes`, except 50, which uses Compose `stop` to preserve its container and external volume. `start` requires a regular preparation lock and managed `.env` link. The wrappers do not orchestrate dependencies or verify inference. Read the relevant stack README before first start.

`status` is read-only and reports the preparation lock separately from live Docker container state and healthchecks. It inspects containers even if the lock or managed `.env` link is missing, so loss of local preparation metadata does not hide a running stack. It distinguishes stopped, partial, degraded, running-without-confirmed-health, and ready services; **a successful `start` is not proof of readiness**. `status --deep` additionally runs Stack 00's platform verifier or an authenticated, read-only PostgreSQL `SELECT 1` for 20 and 30. Other stacks have no additional deep probe yet. Healthchecks establish local service liveness, not end-to-end functionality, model policy, background-job success, or backup validity. See [stack operations](docs/operations.md) for the verb matrix, output interpretation, and first-run exceptions.

## Source and runtime

`STACKS_ROOT` in `.env` identifies the checkout; `BASE_PATH` identifies installation-owned runtime directories. The examples assume `/opt/docker/stacks` for the checkout, but the configured paths govern an actual installation. Stack 00 installation reconciles its platform and Stack 10 prerequisite directories, Docker network, and managed per-stack `.env` links; it leaves other unlocked application service directories alone. Certificates are sourced from mkcert when missing or explicitly rotated; see the [mkcert guide](program_configs/inference_server/mkcert/README.md). Stack 70 backs up the root `.env` as `.env-backup-YYMMDD-HHMMSS` before changing its own defaults or signing secret; it never issues a LiteLLM key.

Before Stack 30 `install`, copy the oMLX API key from the Mac mini into `OMLX_API_KEY` in the protected `.env`; an unset or placeholder key blocks installation. Set the `OMLX_MODEL_*` profiles if your oMLX server does not use the template defaults. Install creates one editable LiteLLM credential and the three database-managed public aliases `mlx/local-general`, `mlx/local-agent`, and `mlx/local-coding`. It also stores separate Hermes inference, Hermes MCP, and Open WebUI keys in `.env`; the MCP key has no server grants until you configure them in LiteLLM. Other models, MCP registrations, and permissions remain operator-managed. Installation does not send a model inference request; that belongs to a later `verify` phase.

## Repository map

| Path | Role |
|---|---|
| `stack-00_-_platform/` … `stack-70_-_open-webui/` | Stack-owned Python packages, Compose files, and configuration |
| `local-ai` | Root dispatcher: `./local-ai stack-NN <verb> [parameters]` |
| `wrapper/bin/stack-NN.py` | Stack-specific operator verbs, also directly invocable |
| `wrapper/lib/stack_status.py` | Shared status and deep-probe implementation |
| `wrapper/stubs/` | Supporting stubs and maintenance utilities; not a unified lifecycle CLI |
| `program_configs/` | Client and infrastructure configuration guides |
| `tests/` | Automated tests grouped by stack and shared behavior |

`./local-ai` dispatches stack wrappers and the protected `env bootstrap` command; it is **not** a cross-stack lifecycle manager, general backup/restore CLI, or upgrade engine. Upgrades and recovery need their own reviewed procedures; do not infer either from a successful preparation lock or healthcheck.

## Validation

```bash
python3 -B tests/run.py
python3 -B .github/workflows/gha_apply_mpl_headers.py --check
python3 -B .github/workflows/gha_apply_python_shebangs.py --check
```

The tests mock external operations; they do not deploy containers or validate a live installation. See [tests/README.md](tests/README.md) and [design principles](docs/design_principles.md).
