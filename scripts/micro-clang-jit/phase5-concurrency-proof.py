"""Phase-5 concurrency qualification involving the micro-Clang backend."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


def _load_base():
    path = Path(__file__).resolve().parents[1] / "tinycc-jit" / "phase4b-concurrency-proof.py"
    spec = importlib.util.spec_from_file_location("_micro_clang_phase5_concurrency_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load shared concurrency harness: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    base = _load_base()
    selector = base.load_shared_selector()
    llvm = base.discover_shared_backend(selector, "llvm-mingw")
    tinycc = base.discover_shared_backend(selector, "tinycc")
    micro = base.discover_shared_backend(selector, "micro-clang")

    result = {
        "schema": 1,
        "status": "pass",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "pairs": [
            base.qualify_pair(selector, micro, micro, args.work_dir, "micro-micro"),
            base.qualify_pair(selector, llvm, micro, args.work_dir, "llvm-micro"),
            base.qualify_pair(selector, tinycc, micro, args.work_dir, "tinycc-micro"),
        ],
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
