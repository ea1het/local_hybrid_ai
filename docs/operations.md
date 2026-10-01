<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
-->

# Stack operations

Run commands from the repository root. First run `sudo ./local-ai env bootstrap` to create or complete the protected root `.env` from [`.env.template`](../.env.template). This command generates missing local secrets, including PostgreSQL administrator passwords, directly in `.env`. PostgreSQL receives its password from `.env`, with no password-file mount. The command preserves existing values, never prints secret values, and creates `.env-backup-YYMMDD-HHMMSS` before changing an existing file. Keep those backups private. Stack 00 creates per-stack `.env` links. Use `sudo` for preparation and container lifecycle operations. `./local-ai stack-NN <verb> [parameters]` dispatches to `wrapper/bin/stack-NN.py` with arguments unchanged; direct invocation of the Python wrapper still works.

The root environment bootstrap generates LiteLLM administrative credentials and salt but cannot generate the Mac mini's oMLX API key. Copy that key into `OMLX_API_KEY` before Stack 30 install. Stack 30 provisions PostgreSQL, configures the three fixed oMLX model aliases and issues separate minimal Hermes/Open WebUI virtual keys into `.env`. The Hermes MCP key initially has no server grants; you configure MCP registrations and permissions in LiteLLM later. Installation does not test inference or end-to-end MCP calls.

| Stack | `install` | `start` | `stop` | `status --deep` |
|---|---|---|---|---|
| 00 | Reconcile bootstrap, network, CA, TLS, then verify and lock | Not applicable | Not applicable | Read-only platform verifier (root required) |
| 10 | HAProxy/Web prepare | Compose `up -d` | Compose `down` | No extra probe |
| 20 | Search/Firecrawl prepare | Compose `up -d` | Compose `down` | Firecrawl PostgreSQL `SELECT 1` |
| 30 | Prepare, provision PostgreSQL, issue minimal keys in a disposable LiteLLM container | Compose `up -d` | Compose `down` | LiteLLM PostgreSQL `SELECT 1` |
| 40 | Prepare and initialize the administrator in disposable Gitea containers | Compose `up -d` | Compose `down` | No extra probe |
| 50 | Check shared network and prepare Dockhand volume; no Stack 00 lock required | Compose `up -d` | Compose **`stop`** | No extra probe |
| 60 | Hermes prepare only | Compose `up -d --build` | Compose `down` | No extra probe |
| 70 | Bootstrap local config, then prepare using the Stack 30-issued LiteLLM key | Compose `up -d` | Compose `down` | No extra probe |

Every wrapper has `install` and `status`; Stacks 10–70 also have `start` and `stop`. Run `sudo ./local-ai stack-NN <verb>` with an available two-digit stack number. `./local-ai --help` lists the current names; an unknown stack is rejected. The wrappers use closed stdin for preparation; they forward output and propagate errors rather than prompting. `stop` is available without a lock; `start` requires one. Neither verb removes persistent bind mounts or the preparation lock. Stack 50's `stop` preserves its existing container and external `dockhand_data` volume; the volume contains runtime state even though Dockhand is reconstructable as a service.

An existing Stack 10–70 `.lock` makes `install` a no-op. Never remove it simply to rerun a command: backup and assess what re-preparation may overwrite first. Stack 00 differs: every `install` audits/repairs platform and Stack 10 prerequisite directories, not other unlocked application directories, and only leaves a lock after successful verification. A direct `stack-00_-_platform/00-bootstrap.py` invocation without `--platform-only` still reconciles all unlocked stacks; review live runtime state first. Certificate rotation is a separate explicit action.

## First deployment and follow-up

1. Prepare Stack 00 and verify with `status --deep` for stacks that require its full platform contract. Supply mkcert source files only if installed certificates are missing or invalid, or when intentionally rotating them. Stack 50 is an exception: its installer checks the existing shared bridge network directly and does not require Stack 00's lock or CA.
2. Set `OMLX_API_KEY` in `.env` before Stack 30 install. Stack 30 installs PostgreSQL and the minimum gateway credentials without leaving its services running. Stack 40 initializes Gitea's administrator during install without starting its long-lived services.
3. Start Stack 30 before consumers. Register optional MCP servers and grant Hermes access in LiteLLM yourself; the installed MCP key starts with no grants. Stack 70 uses the key Stack 30 placed in `.env`; its own bootstrap only backs up and fills local defaults or signing identity.
4. Start applications, inspect `status`, and perform any application-specific readiness or policy checks. Stack 20's `wait-ready.py`, Stack 60's memory/capability setup, and Stack 70's model-policy reconciliation are not automatically run by `start`.

`status` reports preparation separately from live Docker state. It discovers containers by their Compose working-directory label, including former stack directory names. If the checkout moved, it can identify a Compose project through a known container name. It does not read the local Compose file or `.env` link. A missing `.lock` therefore reports `preparation=UNPREPARED` while still showing any running containers and their health; `overall` remains `NOT READY` until preparation is verified. A required container that is running without a healthy healthcheck is `RUNNING`, not `READY`. Stopped, partially started, and unhealthy services are not ready. Optional Compose profiles, such as Stack 60 Git-memory sync, do not count as failures when inactive. A return code of 0 means the wrapper's implemented checks passed; it does **not** prove real search, inference, runner jobs, memory sync, policy convergence, or public TLS routing. `status --deep` is read-only and adds only the probes shown in the table. Docker access is required; an unavailable Docker daemon reports `UNKNOWN`, not `STOPPED`.

The dispatcher and wrappers are per-stack operations, not a dependency scheduler, upgrade engine, or disaster-recovery interface. Consult the [stack READMEs](../README.md#stacks-and-dependencies) before running first-time or destructive procedures.
