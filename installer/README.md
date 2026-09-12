# Installer

The common installer resolves dependency order from manifests and lifecycle commands from `installer/lifecycle.json`. It must remain generic: stack-specific behaviour belongs to the stack, not to `install.py`.

```mermaid
flowchart LR
    Request --> Resolve[Resolve dependencies]
    Resolve --> Prepare --> Deploy --> Ready --> Reconcile --> Verify
    Reconcile -. restart/recreate .-> Ready
```

## Contracts

- `.lock` means PREPARED only.
- Planning is read-only.
- PREPARE may create owned runtime/configuration but must not rewrite the central `.env` as a hidden side effect.
- A healthy running stack is not automatically considered converged with tracked source; explicit drift/upgrade handling remains planned work.
- Required dependencies are installed before their consumer.

## Commands

```bash
python3 install.py plan all
python3 install.py plan 7
python3 install.py 7 --yes
python3 install.py 7 --reconcile --yes
```

The full operator flow is documented in [../docs/installation.md](../docs/installation.md). Automated contracts live only under [../tests/](../tests/).
