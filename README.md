# Local Hybrid AI

Local-first AI platform built as independent Docker stacks. Git contains source and declarative configuration; mutable runtime lives outside the checkout.

```mermaid
flowchart LR
    S0[Stack0 Platform] --> S1[Stack1 HAProxy]
    S0 --> S2[Stack2 Web]
    S0 --> S3[Stack3 LiteLLM]
    S0 --> S4[Stack4 Gitea]
    S0 --> S5[Stack5 Dockhand]
    S0 --> S6[Stack6 Hermes]
    S0 --> S7[Stack7 Open WebUI]
    S3 --> S6
    S3 --> S7
    S2 -. optional web.search / web.extract .-> S6
    S2 -. optional web.search / web.extract .-> S7
    S1 -. ingress .-> S7
```

## Repository contract

```text
/opt/docker/stacks    Git source
/opt/docker/runtime   persistent mutable runtime
```

`.lock` means **PREPARED only**. It never means deployed, ready or healthy. Stack preparation must not silently rewrite the protected root `.env`.

```mermaid
flowchart LR
    P[PREPARE] --> D[DEPLOY] --> R[READY] --> C[RECONCILE] --> V[VERIFY]
    C -. if restart/recreate .-> R
```

## Structure

```text
README.md / LICENSE     repository entry points
docs/                   long-form documentation and evidence
adr/                    architecture decision records
sdr/                    security decision records
openspec/               lightweight Gherkin behaviour contracts
tests/                  all automated tests
installer/              shared lifecycle registry
bkp-dr/                 DR implementation and schemas
stack0_-_* ... stack7_-_*  atomic stack implementations
```

## Operator entry points

Installation is currently driven by `install.py`; backup/restore entry points live under `bkp-dr/`. See [docs/installation.md](docs/installation.md) and [docs/dr/howto.md](docs/dr/howto.md).

```bash
python3 install.py plan all
python3 install.py 0 1 2 3 4 5 6 7 --yes
python3 -m unittest discover -s tests -p 'test_*.py'
```

## Documentation

Start with [docs/README.md](docs/README.md). Architectural decisions live in [adr/](adr/), security decisions in [sdr/](sdr/), behavioural specifications in [openspec/](openspec/) and active work in [docs/pending.md](docs/pending.md).
