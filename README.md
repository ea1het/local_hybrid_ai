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
| [50 · Dockhand](stack-50_-_dockhand/README.md) | Optional Docker management UI | 00; 10 for optional ingress |
| [60 · Hermes](stack-60_-_hermes/README.md) | Agent, sandbox, and maintenance sidecars | 00 and running 30; 20 and 40 optional |
| [70 · Open WebUI](stack-70_-_open-webui/README.md) | Chat UI over LiteLLM | 00 and running 30; 10 and 20 optional |

Stack 00 owns common host prerequisites. Stack 20 is an optional provider, not an automatic external-web fallback. Stack 30 is the required gateway for AI consumers. Each stack README describes its specific state and manual follow-up steps.

## Installation and operations

Run the wrappers from the repository root with Python 3 and Docker Compose available. Prepare the protected `.env` using [`.env.template`](.env.template); do not commit credentials. Initial preparation and lifecycle commands need root privileges. For example:

```bash
cd /opt/docker/stacks
sudo python3 -B wrapper/bin/stack-00.py install
sudo python3 -B wrapper/bin/stack-00.py status --deep
sudo python3 -B wrapper/bin/stack-10.py install
sudo python3 -B wrapper/bin/stack-10.py start
sudo python3 -B wrapper/bin/stack-10.py status
sudo python3 -B wrapper/bin/stack-10.py stop
```

Replace `10` with `20`, `30`, `40`, `50`, `60`, or `70` for their wrappers. Stack 00 has **`install` and `status` only**: it has no containers to start or stop. Stack 00 `install` audits and repairs missing platform prerequisites even when `.lock` exists, and writes/retains its lock only after verification. Other stacks' `install` normally stops at an existing `.lock`; removing a lock can trigger destructive reconfiguration and requires a deliberate review and backup. A lock means **prepared**, never running or healthy.

For Stacks 10–70, `install` prepares but does not start containers. `start` runs Compose `up -d` (`--build` for 60); `stop` runs Compose `down` without `--volumes`, except 50, which uses Compose `stop` to preserve its container and external volume. `start` requires a regular preparation lock and managed `.env` link. These verbs do not automatically orchestrate dependent stacks or all first-deployment tasks. In particular, 30 needs separate PostgreSQL provisioning, 40 needs its deployment script, and 70 needs **running LiteLLM** to issue a scoped API key when one is missing. Read the relevant stack README before first start.

`status` is read-only and combines the lock with Docker Compose container state and healthchecks. It distinguishes stopped, partial, degraded, running-without-confirmed-health, and ready services; **a successful `start` is not proof of readiness**. `status --deep` additionally runs Stack 00's platform verifier or an authenticated, read-only PostgreSQL `SELECT 1` for 20 and 30. Other stacks have no additional deep probe yet. Healthchecks establish local service liveness, not end-to-end functionality, model policy, background-job success, or backup validity. See [stack operations](docs/operations.md) for the verb matrix, output interpretation, and first-run exceptions.

## Source and runtime

`STACKS_ROOT` in `.env` identifies the checkout; `BASE_PATH` identifies installation-owned runtime directories. The examples assume `/opt/docker/stacks` for the checkout, but the configured paths govern an actual installation. Stack 00 creates the common directory tree, Docker network, and managed per-stack `.env` links. Certificates are sourced from mkcert when missing or explicitly rotated; see the [mkcert guide](program_configs/inference_server/mkcert/README.md). Stack 70 backs up the root `.env` as `.env-backup-YYMMDD-HHMMSS` before changing it and stores its LiteLLM virtual key there without printing it.

## Repository map

| Path | Role |
|---|---|
| `stack-00_-_platform/` … `stack-70_-_open-webui/` | Stack-owned Python packages, Compose files, and configuration |
| `wrapper/bin/stack-NN.py` | Operator verbs for each stack |
| `wrapper/lib/stack_status.py` | Shared status and deep-probe implementation |
| `wrapper/stubs/` | Supporting stubs and maintenance utilities; not a unified lifecycle CLI |
| `program_configs/` | Client and infrastructure configuration guides |
| `tests/` | Automated tests grouped by stack and shared behavior |

The repository does **not** currently provide a unified `./local-ai` management command, backup/restore CLI, or automatic cross-stack lifecycle manager. Do not use older commands for those interfaces. Upgrades and recovery need their own reviewed procedures; do not infer either from a successful preparation lock or healthcheck.

## Validation

```bash
python3 -B tests/run.py
python3 -B .github/workflows/gha_apply_mpl_headers.py --check
python3 -B .github/workflows/gha_apply_python_shebangs.py --check
```

The tests mock external operations; they do not deploy containers or validate a live installation. See [tests/README.md](tests/README.md) and [design principles](docs/design_principles.md).
