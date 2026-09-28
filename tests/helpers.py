"""Load operational stack scripts without requiring importable filenames."""

import importlib.util
import sys

sys.dont_write_bytecode = True
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(stack: str, filename: str):
    path = ROOT / stack / filename
    qualified = filename.removesuffix(".py").replace("/", "_").replace("-", "_")
    name = f"test_{stack.split('_')[0]}_{qualified}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module
