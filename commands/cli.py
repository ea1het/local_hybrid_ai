# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Public command dispatcher behind the root ``./local-ai`` entry point."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from commands import completion, doctor, install_entry, inventory, runtime_lifecycle, status, upgrade_adopt, upgrade_entry

ROOT = Path(__file__).resolve().parents[1]
RECOVERY = ROOT / "commands" / "recovery"
SCHEMA_VERSION = "1"


def _run_internal(path: Path, args: list[str]) -> int:
    return subprocess.run([sys.executable, str(path), *args], cwd=ROOT).returncode


def _json_error(code: str, message: str, *, command: str | None = None) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "success": False,
        "error": {"code": code, "message": message},
    }
    if command:
        payload["command"] = command
    print(json.dumps(payload, indent=2, sort_keys=True))


def _stack_selector_error(token: str, *, json_output: bool, command: str) -> int:
    message = f"stack selector must be a numeric id such as 7, not {token!r}"
    if json_output:
        _json_error("STACK_SELECTOR_INVALID", message, command=command)
    else:
        print(f"ERROR [STACK_SELECTOR_INVALID]: {message}", file=sys.stderr)
    return 2


def _upgrade_public_args(args: list[str]) -> tuple[list[str] | None, str | None]:
    """Translate the numeric public stack selector to the internal manifest id."""
    if not args or args[0] in {"--offline", "--yes", "check", "adopt"}:
        return list(args), None

    translated = list(args)
    stack_pos = 1 if translated[0] == "policy" else 0
    if len(translated) <= stack_pos:
        return translated, None

    token = translated[stack_pos]
    if not token.isdigit():
        return None, token
    translated[stack_pos] = f"stack{int(token)}"
    return translated, None


def _run_internal_json(path: Path, args: list[str], *, command: str) -> int:
    cp = subprocess.run(
        [sys.executable, str(path), *args, "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if cp.returncode != 0:
        detail = (cp.stderr or cp.stdout or f"{command} failed").strip()
        _json_error("INTERNAL_COMMAND_FAILED", detail, command=command)
        return cp.returncode
    try:
        result = json.loads(cp.stdout)
    except json.JSONDecodeError:
        _json_error(
            "INTERNAL_JSON_INVALID",
            f"private implementation for {command} returned invalid JSON",
            command=command,
        )
        return 1
    print(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "success": True,
        "result": result,
    }, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-ai",
        description="Supported management CLI for the Local Hybrid AI installation",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("install", help="install or reconcile stacks")

    backup = sub.add_parser("backup", help="create a recovery point")
    backup.add_argument("args", nargs=argparse.REMAINDER)

    restore = sub.add_parser("restore", help="disaster-recovery operations")
    restore.add_argument("args", nargs=argparse.REMAINDER)

    sub.add_parser("status", help="show operational stack state, runtime health and drift")
    sub.add_parser("doctor", help="diagnose management prerequisites and environment consistency")
    sub.add_parser("inventory", help="validate and rescan manifest-declared component topology")
    sub.add_parser("completion", help="emit Bash or Zsh completion integration")

    for action in ("start", "stop"):
        runtime = sub.add_parser(action, help=f"{action} one prepared stack runtime")
        runtime.add_argument("stack", help="numeric stack id, for example 7")

    sub.add_parser("upgrade", help="inspect versions and manage component upgrades")

    return parser


def restore_command(args: list[str], json_output: bool) -> int:
    if not args:
        if json_output:
            _json_error(
                "RESTORE_ACTION_REQUIRED",
                "restore requires one of plan, drill, apply or resume",
                command="restore",
            )
        else:
            print("Usage: ./local-ai restore <plan|drill|apply|resume> ...", file=sys.stderr)
        return 2
    action, *rest = args
    mapping = {
        "plan": RECOVERY / "restore-all.py",
        "drill": RECOVERY / "restore-drill.py",
        "apply": RECOVERY / "restore-live.py",
        "resume": RECOVERY / "restore-resume.py",
    }
    script = mapping.get(action)
    if script is None:
        if json_output:
            _json_error(
                "RESTORE_ACTION_UNKNOWN",
                f"unknown restore action: {action}",
                command="restore",
            )
        else:
            print(f"Unknown restore action: {action}", file=sys.stderr)
        return 2
    if json_output:
        return _run_internal_json(script, rest, command=f"restore.{action}")
    return _run_internal(script, rest)


def _upgrade_adopt(args: list[str], *, json_output: bool) -> int:
    try:
        return upgrade_adopt.main(args, json_output=json_output)
    except upgrade_adopt.AdoptionError as exc:
        if json_output:
            print(json.dumps({
                "schema_version": upgrade_adopt.SCHEMA_VERSION,
                "command": "upgrade.adopt",
                "success": False,
                "error": {"code": exc.code, "message": str(exc)},
            }, indent=2, sort_keys=True))
        else:
            print(f"UPGRADE ERROR [{exc.code}]: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    json_output = "--json" in raw
    raw = [arg for arg in raw if arg != "--json"]

    # Shell completion is an intentionally private, read-only source query.
    # It is routed before argparse and before every runtime/registry facade.
    if raw and raw[0] == "__complete":
        try:
            print("\n".join(completion.complete(raw[1:])))
            return 0
        except Exception:
            # TAB must fail quiet rather than disrupt the interactive shell.
            return 0

    if raw and raw[0] == "completion":
        return completion.main(raw[1:])

    if raw and raw[0] == "install":
        if json_output:
            return install_entry.main(raw[1:])
        return _run_internal(ROOT / "commands" / "install.py", raw[1:])

    if raw and raw[0] == "backup":
        args = list(raw[1:])
        if json_output and "--json" not in args:
            args.append("--json")
        return _run_internal(RECOVERY / "backup-all.py", args)

    if raw and raw[0] == "inventory":
        return inventory.main(raw[1:], json_output=json_output)

    if raw and raw[0] == "upgrade":
        if len(raw) >= 2 and raw[1] == "adopt":
            return _upgrade_adopt(raw[2:], json_output=json_output)
        upgrade_args, invalid = _upgrade_public_args(raw[1:])
        if invalid is not None:
            return _stack_selector_error(invalid, json_output=json_output, command="upgrade")
        return upgrade_entry.main(upgrade_args or [], json_output=json_output)

    parser = build_parser()
    ns = parser.parse_args(raw)
    if ns.command is None:
        parser.print_help()
        return 0

    if ns.command == "backup":
        args = list(ns.args)
        if json_output and "--json" not in args:
            args.append("--json")
        return _run_internal(RECOVERY / "backup-all.py", args)

    if ns.command == "restore":
        return restore_command(ns.args, json_output)

    if ns.command == "status":
        return status.main(json_output=json_output)

    if ns.command == "doctor":
        return doctor.main(json_output=json_output)

    if ns.command == "inventory":
        return inventory.main([], json_output=json_output)

    if ns.command in {"start", "stop"}:
        if not ns.stack.isdigit():
            return _stack_selector_error(ns.stack, json_output=json_output, command=ns.command)
        return runtime_lifecycle.main(ns.command, ns.stack, json_output=json_output)

    parser.error("unsupported command")
    return 2
