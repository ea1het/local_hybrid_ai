from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from commands import status, upgrade_entry

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "1"


def _run_internal(path: Path, args: list[str]) -> int:
    return subprocess.run([sys.executable, str(path), *args], cwd=ROOT).returncode


def _json_error(code: str, message: str) -> None:
    print(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "success": False,
        "error": {"code": code, "message": message},
    }, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-ai",
        description="Supported management CLI for the Local Hybrid AI installation",
    )
    sub = parser.add_subparsers(dest="command")

    install = sub.add_parser("install", help="install or reconcile stacks")
    install.add_argument("args", nargs=argparse.REMAINDER)

    backup = sub.add_parser("backup", help="create a recovery point")
    backup.add_argument("args", nargs=argparse.REMAINDER)

    restore = sub.add_parser("restore", help="disaster-recovery operations")
    restore.add_argument("args", nargs=argparse.REMAINDER)

    sub.add_parser("status", help="show desired, deployed and actual component state")

    up = sub.add_parser("upgrade", help="inspect and manage the local upgrade plan")
    up.add_argument(
        "--yes",
        action="store_true",
        dest="upgrade_yes",
        help="apply exactly the upgrades already selected in the local plan",
    )
    up.add_argument("args", nargs=argparse.REMAINDER)

    return parser


def restore_command(args: list[str], json_output: bool) -> int:
    if not args:
        print("Usage: ./local-ai restore <plan|drill|apply|resume> ...", file=sys.stderr)
        return 2
    action, *rest = args
    mapping = {
        "plan": ROOT / "bkp-dr" / "restore-all.py",
        "drill": ROOT / "bkp-dr" / "restore-drill.py",
        "apply": ROOT / "bkp-dr" / "restore-live.py",
        "resume": ROOT / "bkp-dr" / "restore-resume.py",
    }
    script = mapping.get(action)
    if script is None:
        print(f"Unknown restore action: {action}", file=sys.stderr)
        return 2
    if json_output and "--json" not in rest:
        rest.append("--json")
    return _run_internal(script, rest)


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    json_output = "--json" in raw
    raw = [arg for arg in raw if arg != "--json"]

    parser = build_parser()
    ns = parser.parse_args(raw)
    if ns.command is None:
        parser.print_help()
        return 0

    if ns.command == "install":
        if json_output:
            _json_error("JSON_NOT_SUPPORTED", "install does not yet expose the stable JSON contract")
            return 2
        return _run_internal(ROOT / "installer" / "install.py", ns.args)

    if ns.command == "backup":
        args = list(ns.args)
        if json_output and "--json" not in args:
            args.append("--json")
        return _run_internal(ROOT / "bkp-dr" / "backup-all.py", args)

    if ns.command == "restore":
        return restore_command(ns.args, json_output)

    if ns.command == "status":
        return status.main(json_output=json_output)

    if ns.command == "upgrade":
        args = list(ns.args)
        if ns.upgrade_yes:
            args.insert(0, "--yes")
        return upgrade_entry.main(args, json_output=json_output)

    parser.error("unsupported command")
    return 2
