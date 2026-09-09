# A2A Knowledge — Local Hybrid AI

> Audience: AI assistants, coding agents and future maintainers.
>
> Read this before modifying the project. Then inspect the current root README, `INSTALLATION.md`, `.env.template`, `.env.secretsexplained.md`, the affected stack README, manifest, Compose file and lifecycle scripts.

## 1. What this project is

`local_hybrid_ai` is a local-first hybrid AI platform composed of atomic Docker stacks with explicit ownership, dependencies, capabilities, readiness and security boundaries.

The platform is not one monolithic Compose application. Each stack owns its own mutable state; Stack0 owns only platform-shared resources.

Core principles:

- local-first operation;
- explicit cloud use rather than silent fallback;
- source/runtime separation;
- atomic stack ownership;
- dependency/capability-driven installation;
- readiness before capability use;
- persistent identity preservation;
- least privilege between services;
- bounded, reversible maintenance.

## 2. Filesystem contract

```text
/opt/docker/
├── stacks/                     # Git source
│   ├── .env                    # operational, ignored by Git
│   ├── .env.template
│   ├── .env.secretsexplained.md
│   ├── install.py
│   ├── installer/
│   └── stack0 ... stack6/
└── runtime/                    # persistent mutable state
```

Reference deployment context:

```dotenv
STACKS_ROOT=/opt/docker/stacks
BASE_PATH=/opt/docker/runtime
NETWORK_NAME=redlocal
```

Never solve a source problem by deleting runtime. Never move mutable production state into Git.

## 3. Stack map

| Stack | Directory | Purpose | Required dependencies | Capabilities |
|---|---|---|---|---|
| 0 | `stack0_-_platform` | platform foundation | none | environment, network, PKI |
| 1 | `stack1_-_haproxy_web` | ingress/static web | 0 | `ingress.https`, `web.static` |
| 2 | `stack2_-_searxng_firecrawl` | local web search/extraction | 0 | `web.search`, `web.extract` |
| 3 | `stack3_-_litellm` | model/MCP policy gateway | 0 | `ai.gateway`, `ai.mcp-gateway` |
| 4 | `stack4_-_gitea` | Git + runner | 0 | `git.remote`, `git.runner` |
| 5 | `stack5_-_dockhand` | container management | 0 | `containers.management` |
| 6 | `stack6_-_hermes` | agent + sandbox + memory | 0, 3 | `ai.agent`, `ai.sandbox`, `ai.memory` |

Stack2 and Stack4 are optional providers for Stack6. Do not turn optional relationships into hidden required dependencies.

## 4. Lifecycle model

```text
PREPARE     create/validate stack-owned resources
DEPLOY      establish required process/container state
READY       prove the capability is usable
RECONCILE   adapt consumer-owned configuration to optional capabilities
VERIFY      validate the resulting stack contract
```

`.lock` means PREPARED only. `running` does not automatically mean READY.

Stack2 is the canonical readiness lesson: provider recovery must wait until both SearXNG and Firecrawl accept connections before Stack6 web capability is reconciled.

## 5. Manifest model

Stack manifests are architectural truth for dependency/capability/ownership relationships.

Important fields:

- `requires`;
- `target_requires`;
- `optional`;
- `provides`;
- `consumes`;
- `optional_consumes`;
- `owns`;
- `atomic`;
- `blockers`.

Do not encode dependency folklore in `install.py`.

## 6. Common installer

`install.py`:

1. validates manifests/lifecycle registry;
2. resolves dependency closure;
3. observes PREPARED state from `.lock`;
4. observes DEPLOYED state from required containers;
5. schedules PREPARE/DEPLOY only when needed;
6. runs provider readiness where declared;
7. treats actual provider transitions as capability changes;
8. discovers prepared optional consumers generically;
9. invokes consumer-owned reconciliation;
10. verifies the resulting contract.

A healthy requested provider should remain verification-only. `--reconcile` is an explicit operator override.

The common installer never rewrites `.env`, deletes `.lock`, resets runtime, prunes Docker or executes historical migrations.

## 7. Cleanup doctrine

The active repository represents the current clean-install architecture only.

Keep:

- installation code;
- current lifecycle/readiness/reconciliation scripts;
- manifests/tests;
- current operational documentation.

Remove completed one-time migration helpers and active documentation that tells operators to run them after the platform has converged. Git history is the historical record.

Do not confuse repository cleanup with runtime destruction. Deleting runtime data, backups or rollback material is a separate bounded operator decision.

## 8. PostgreSQL security standard

Where an application stack owns PostgreSQL, separate administrative and application identities.

```text
postgres         administrative/bootstrap role
application role normal runtime connectivity
```

The application must not use `postgres` in normal operation.

Administrative passwords that normal consumers do not need should live as restricted stack-owned runtime secrets outside shared `.env`.

### Stack2

```text
firecrawl-postgres / database postgres
├── postgres
│   SUPERUSER / bootstrap / owner / pg_cron
│   ${BASE_PATH}/service_-_firecrawl-postgres/secret/postgres_admin_password
└── firecrawl
    non-admin application role
    FIRECRAWL_DB_PASSWORD in protected .env
```

The database remains `postgres` because the pinned NuQ PostgreSQL image configures `pg_cron` for that database. Firecrawl connects as `firecrawl` over `redlocal`; no PostgreSQL host port is published.

Fresh installation order inside PostgreSQL initialization:

1. upstream `010-nuq.sql` creates NuQ objects;
2. Stack2 `config/postgres/020-firecrawl-app-role.sh` creates/reconciles `firecrawl`;
3. application receives required schema/table/sequence privileges and default privileges;
4. `postgres` retains ownership/cron administration.

### Stack3

```text
litellm-postgres
├── postgres
│   admin/bootstrap
│   ${BASE_PATH}/service_-_litellm-postgres/secret/postgres_admin_password
└── ${LITELLM_DB_USER}
    LiteLLM application role
    LITELLM_DB_PASSWORD
```

Stack3 and Stack2 now follow the same identity principle even though their bootstrap mechanisms differ.

## 9. PGDATA safety

Existing PGDATA is persistent identity. PREPARE may validate it but must not recursively `chown`, replace, reset or recreate it for convenience.

After maintenance, test real DB operations and application connectivity. Container health alone is insufficient evidence.

## 10. Stack0

Stack0 owns platform-shared contracts:

- central environment compatibility links;
- `redlocal`;
- platform runtime;
- PKI;
- manifest discovery/validation.

PKI private key is persistent identity and must not rotate implicitly.

## 11. Stack1

Stack1 owns HAProxy/static web. Backends are optional from Stack1's dependency perspective. It may route to services that are absent at install time.

Do not make Stack1 own application runtime merely because it exposes an application.

## 12. Stack2

Provides local `web.search` and `web.extract`.

Important rules:

- requires only Stack0;
- owns all Firecrawl supporting services including PostgreSQL;
- does not create `redlocal`;
- PostgreSQL app/admin roles are separate;
- existing PGDATA metadata is preserved;
- readiness gate is `02-wait-ready.sh`;
- absence must leave consumers fail-closed for local web.

## 13. Stack3

LiteLLM is the AI policy boundary for inference and MCP. Stack6 requires it. Stack3 owns its dedicated PostgreSQL and uses a dedicated application DB identity distinct from `postgres`.

`LITELLM_SALT_KEY` is persistent cryptographic identity. Do not rotate it casually.

## 14. Stack4

Gitea/runner stack. Preserve Gitea data, runner identity and registration secret. Web health does not prove Git-over-SSH health.

## 15. Stack5

Dockhand owns external volume `dockhand_data`. Preserve existing volume state.

## 16. Stack6

Requires Stack0 + Stack3. Optionally consumes Stack2 web capabilities and Stack4 `git.remote`.

Security boundary:

- no Docker socket in Hermes;
- execution over SSH to isolated sandbox;
- sandbox not attached to `redlocal`;
- cleanup sidecar has no network;
- Git memory synchronization has explicit operator intent separate from provider availability.

## 17. Secrets doctrine

Read `.env.secretsexplained.md` before creating or changing secrets.

Differentiate:

- operator-generated random values;
- application-native generated secrets;
- service-issued credentials;
- external-provider credentials;
- runtime-generated identities;
- operator-provisioned runtime identities;
- derived secrets.

A generator existing does not make a persistent secret disposable.

## 18. Shell safety for operator commands

The operator pastes command blocks into an existing interactive shell.

Do not include global interactive-shell constructs that can terminate it, such as:

```bash
set -e
set -Eeuo pipefail
exit
exec ...
```

Repository scripts executed as child processes may use strict shell options.

Interactive diagnostic/migration blocks should capture return codes, branch explicitly, avoid broad cleanup and end visibly with:

```bash
echo "La shell permanece abierta."
```

## 19. How to modify the project

Before changing code:

1. identify owning stack;
2. inspect current source and runtime contract;
3. list invariants that must remain unchanged;
4. make the smallest ownership-correct change;
5. validate source before runtime;
6. preserve availability and persistent state;
7. test the real feature/failure path;
8. verify invariants again;
9. update documentation in the same work;
10. leave Git and deployed host on the same intended commit when deployment is in scope.

Typical source checks:

```bash
bash -n <script>
docker compose config --quiet
python3 stack0_-_platform/manifests.py validate
python3 stack0_-_platform/manifests.py validate --target
python3 -m unittest -v installer.test_installer
git diff --check
```

## 20. Things not to do casually

Do not:

- `docker compose down -v`;
- broad Docker prune;
- delete `/opt/docker/runtime`;
- reset databases to fix configuration;
- rotate persistent secrets because regeneration is easy;
- overwrite `.env` from `.env.template`;
- print secrets/effective secret-bearing config;
- recursively `chown` PostgreSQL PGDATA;
- give Hermes Docker socket access;
- attach sandbox to `redlocal` without explicit redesign;
- silently enable cloud fallback;
- hard-code dependencies that belong in manifests;
- retain completed migration helpers as permanent installation surface.

## 21. Next planned stack — Open WebUI

Open WebUI should be a new atomic stack. Before implementation define:

- stack ID/directory;
- runtime ownership;
- required/optional dependencies;
- consumed/provided capabilities;
- database/storage model;
- secret provenance;
- application readiness;
- ingress relationship with Stack1;
- tests and docs.

Do not add Open WebUI-specific conditionals to the generic installer unless the manifest/lifecycle model genuinely cannot express the requirement.

## 22. Completion checklist

Before claiming work complete:

- source is on intended commit;
- worktree is clean;
- manifests validate;
- installer tests pass when relevant;
- operational `.env` remains protected and preserved;
- runtime identities remain intact;
- required containers are running;
- readiness passes;
- actual application path works;
- no obsolete active migration helper remains;
- documentation matches current code;
- deployed host is synchronized to the same commit if deployment was part of the task.

The platform's maintenance principle is simple: capability must be explicit, bounded, ready before use and under operator control.
