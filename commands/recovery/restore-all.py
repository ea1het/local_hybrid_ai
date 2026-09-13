#!/usr/bin/env python3
"""Read-only CLI for the generic restore-all planner."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import dr_restore_all


def print_human(plan: dr_restore_all.RestorePlan) -> None:
    print("Restore all dry-run")
    print(f"- backup set: {plan.backup_set}")
    print(f"- source commit: {plan.source_commit}")
    print("- resolved stacks: " + " -> ".join(f"stack{sid}" for sid in plan.resolved_stacks))
    print(f"- checksums verified: {plan.checksums_verified}")
    print("Ordered restore actions:")
    current = None
    for action in plan.actions:
        if action.phase != current:
            current = action.phase
            print(f"\n[{current}]")
        scope = "platform" if action.stack_id is None else f"stack{action.stack_id}"
        resource = f" {action.resource_id}" if action.resource_id else ""
        strategy = f" [{action.strategy}]" if action.strategy else ""
        print(f"- {scope}{resource}: {action.kind}{strategy} — {action.detail}")
    print("\nNo changes made.")
    print("This command validates the recovery point and restore ordering only; it does not restore or deploy anything.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan and preflight a full manifest-driven restore")
    parser.add_argument("backup_set", help="completed full backup-set directory")
    parser.add_argument("--dry-run", action="store_true", help="required: validate and show restore ordering without writes")
    parser.add_argument("--json", action="store_true", help="emit machine-readable plan")
    args = parser.parse_args()

    if not args.dry_run:
        print("ERROR: real restore execution is intentionally blocked in this milestone; use --dry-run", file=sys.stderr)
        return 2
    try:
        plan = dr_restore_all.plan_restore_all(Path(args.backup_set))
    except (dr_restore_all.RestoreAllError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(plan.as_dict(), indent=2, sort_keys=True))
    else:
        print_human(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
