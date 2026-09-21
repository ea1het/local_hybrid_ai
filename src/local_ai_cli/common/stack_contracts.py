#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Loader for stack-owned structured management payload contracts."""

from __future__ import annotations
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class StackContractError(RuntimeError):
    pass


def json_payload(stack_id: int, directory: str, **state):
    """Return one stack-owned payload without allowing the stack to render it."""
    path = ROOT / directory / "cli_contract.py"
    if not path.is_file():
        raise StackContractError(f"stack{stack_id} is missing cli_contract.py")
    spec = importlib.util.spec_from_file_location(f"local_ai_stack{stack_id}_cli_contract", path)
    if spec is None or spec.loader is None:
        raise StackContractError(f"cannot load stack{stack_id} CLI contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    builder = getattr(module, "json_payload", None)
    if not callable(builder):
        raise StackContractError(f"stack{stack_id} CLI contract has no json_payload()")
    payload = builder(**state)
    if not isinstance(payload, dict) or payload.get("stack") != f"stack{stack_id}":
        raise StackContractError(f"stack{stack_id} returned an invalid CLI payload")
    return payload
