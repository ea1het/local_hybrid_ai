# Upgrade compatibility policy

Container registry discovery answers **what exists**. Compatibility policy answers **what this installation permits local-ai to treat as an upgrade target**. These are deliberately separate decisions.

The supported policy vocabulary is intentionally small:

| Policy | Automatic compatibility boundary |
|---|---|
| `minor-series` | strictly newer target in the same `major.minor` series |
| `major-series` | strictly newer target in the same `major` series |
| `manual` | no series inference; the operator explicitly names the exact target |

`manual` is not a disabled state. The exact target must still exist in the same configured container registry/package. When current and target are comparable semantic versions, a downgrade is rejected. Non-semantic identities are accepted only as explicit manual choices and remain subject to registry and executor validation.

## Project default and installation override

Each component in `internal/upgrade-components.json` has a project `default_policy`. An installation may override it without modifying Git or `.env`.

Mutable overrides live at:

```text
/opt/docker/runtime/platform/upgrade-policy.json
```

The effective policy is the local override when one exists; otherwise the catalog default applies.

Inspect all policies:

```bash
./local-ai upgrade policy
```

Inspect one component:

```bash
./local-ai upgrade policy stack4 gitea
```

Set any of the three policies:

```bash
./local-ai upgrade policy stack4 gitea set minor-series
./local-ai upgrade policy stack4 gitea set major-series
./local-ai upgrade policy stack4 gitea set manual
```

For a stack containing exactly one component, the component name may be omitted:

```bash
./local-ai upgrade policy stack7 set major-series
```

Remove only the local override:

```bash
./local-ai upgrade policy stack4 gitea clear
```

`clear` does not introduce a fourth policy and does not delete an upgrade selection. It makes the catalog `default_policy` effective again.

## Policy and selectable are independent

Compatibility and executor capability are different gates. A component can have `major-series` policy and still be `selectable: false`. In that case local-ai may describe its compatibility policy, but the component cannot be selected through the supported executor.

This is intentional for components whose safe upgrade mechanism has not yet been qualified. In particular, changing a policy does not make an inventory-only component executable.

## Selection validation

A selection must pass all relevant gates:

```text
exact target exists in configured registry/package
        ↓
component is selectable
        ↓
target is not already current
        ↓
effective compatibility policy permits target
        ↓
selection is persisted locally
```

Stable rejection codes include:

- `UPGRADE_COMPONENT_NOT_SELECTABLE`
- `UPGRADE_TARGET_NOT_AVAILABLE`
- `UPGRADE_TARGET_NOT_NEWER`
- `UPGRADE_TARGET_UNSUPPORTED`

Availability in `upgrade check` is therefore discovery state, not upgrade authorization.

## Existing selections and policy changes

Changing policy never silently clears a selected target. If an existing selection no longer satisfies the new effective policy, `upgrade policy` reports it with `VALID=no`; the selection remains in `upgrade-plan.json` for traceability.

`./local-ai upgrade --yes` revalidates the current effective policy and fails with `UPGRADE_TARGET_UNSUPPORTED` before target preflight, backup or desired-state mutation when the selection is no longer allowed.

## Machine-readable contract

Policy commands support the standard CLI JSON mode:

```bash
./local-ai --json upgrade policy
./local-ai --json upgrade policy stack4 gitea
./local-ai --json upgrade policy stack4 gitea set manual
./local-ai --json upgrade policy stack4 gitea clear
```

A component policy record includes `default_policy`, `override_policy`, `effective_policy`, `selectable`, `selected` and `selection_valid`. Mutating responses also expose `previous_effective_policy` and the action performed.

The JSON contract version is independent from the internal implementation and policy-state file schema.
