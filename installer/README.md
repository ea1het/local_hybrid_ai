# Common installer v1

This directory contains orchestration metadata/tests for the repository-level installer. Architectural dependency and capability truth remains in each stack's `manifest.json`; this directory must not become a second dependency graph.

## Entry points

Canonical portable entry point:

```bash
python3 install.py <selectors> [--plan|--dry-run] [--target] [--reconcile] [--yes]
```

Portable shell wrapper:

```bash
bash ./install.sh ...
```

Do not assume the root wrapper has an executable bit in every checkout.

## State model

```text
PREPARED  -> stack .lock exists
DEPLOYED  -> every required container is running
READY     -> generic runtime readiness plus stack-specific readiness where declared
RECONCILE -> consumer-owned adaptation to changed optional capabilities
VERIFY    -> stack-owned contract validation
```

`PREPARED`, `DEPLOYED` and `READY` are deliberately different concepts.

## Runtime readiness

After any DEPLOY transition, `install.py` inserts an internal `ready` action before proceeding to later dependency stacks or capability reconciliation.

Generic runtime readiness rules:

- required container with no Docker healthcheck: `running` is the baseline runtime-ready state;
- required container with a Docker healthcheck: wait for `running/healthy`;
- `running/starting` waits, bounded by the installer timeout;
- absent/exited/dead required containers fail before reconciliation;
- timeout fails closed.

Generic runtime readiness is only a baseline. A stack that needs application-level evidence owns an additional lifecycle command. Stack2 is the current example: `02-wait-ready.sh` verifies that SearXNG and Firecrawl actually accept connections before `web.search`/`web.extract` are reconciled into Stack6.

## Action ordering

For a stack that needs convergence:

```text
PREPARE (only when not prepared)
DEPLOY  (only when required containers are not deployed)
READY   (generic runtime wait after DEPLOY; stack deploy commands may add stronger readiness)
```

After all dependency/provider transitions are ready:

```text
RECONCILE affected prepared consumers
VERIFY dependency plan + reconciled consumers
final required-runtime validation
```

A stable provider does not count as a changed capability merely because it was requested. `--reconcile` is the explicit operator override for a requested consumer that owns reconciliation.

## Lifecycle registry

`lifecycle.json` maps stack IDs to:

- `directory`;
- `required_containers`;
- `prepare` commands;
- `deploy` commands;
- `reconcile` commands;
- `verify` commands.

`required_containers` must be a subset of containers owned by the stack manifest.

Commands beginning with `./` are executed with `bash` inside the owning stack directory. This avoids relying on executable bits for repository-created lifecycle scripts while preserving strict shell behavior inside the scripts themselves.

## Tests

```bash
python3 -m unittest -v installer.test_installer
```

The suite covers:

- healthy requested consumer -> verify only;
- fresh consumer -> prepare/deploy/ready/reconcile;
- healthy provider -> no spurious consumer reconciliation;
- changed web/git provider -> ready before consumer reconciliation;
- explicit `--reconcile` override;
- runtime health transition `starting -> healthy`;
- fail-fast behavior for an exited required container.

## Adding the planned Open WebUI stack

Do not add Open-WebUI-specific branching to `install.py`.

The implementation sequence should be:

1. design the stack ownership/dependencies/capabilities first;
2. add `stackN_-_<name>/manifest.json`;
3. add the exact Stack ID to `lifecycle.json` with stack-owned lifecycle commands;
4. define `required_containers`;
5. add an application-level HTTP readiness script if container state/health is not sufficient;
6. add planner/lifecycle regression tests;
7. validate current and target manifest graphs;
8. update root, installation, Stack1/ingress if applicable, new stack docs and `a2aknowledge.md`.

The manifest resolver dynamically discovers stack directories, so a correctly modeled new stack should be selectable by ID, `stackN`, exact directory name and `all` without changing dependency resolution code.
