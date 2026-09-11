"""Verify MPI child processes resolve the same hermetic FEniCS JIT runtime."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path


def _load_runtime(toolchain_root: Path):
    path = toolchain_root / "runtime" / "fenics_jit_runtime.py"
    spec = importlib.util.spec_from_file_location("fenics_jit_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load packaged JIT runtime helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--toolchain-root", required=True)
    parser.add_argument("--python-prefix", required=True)
    parser.add_argument("--diagnostics-dir", required=True)
    args = parser.parse_args()

    toolchain_root = Path(args.toolchain_root).resolve()
    python_prefix = Path(args.python_prefix).resolve()
    diagnostics = Path(args.diagnostics_dir).resolve()
    diagnostics.mkdir(parents=True, exist_ok=True)

    runtime = _load_runtime(toolchain_root)
    config = runtime.RuntimeConfig.discover(
        toolchain_root=toolchain_root,
        python_prefix=python_prefix,
    )

    with config.activate(verbose=True):
        from mpi4py import MPI

        comm = MPI.COMM_WORLD
        rank = comm.Get_rank()
        size = comm.Get_size()

        record = config.diagnostic_record()
        selected = {
            "backend": record["backend"],
            "target": record["target"],
            "crt": record["crt"],
            "toolchain_root": record["toolchain_root"],
            "clang": record["clang"],
            "python_include": record["python_include"],
            "python_import_library": record["python_import_library"],
            "ffcx_include": record["ffcx_include"],
            "CC": os.environ.get("CC"),
            "CXX": os.environ.get("CXX"),
            "PATH": os.environ.get("PATH"),
            "FFCX_CFFI_COMPILER_BACKEND": os.environ.get(
                "FFCX_CFFI_COMPILER_BACKEND"
            ),
        }
        gathered = comm.allgather(selected)

        if size < 2:
            raise RuntimeError(f"MPI runtime proof requires at least 2 ranks, got {size}")
        if any(item != gathered[0] for item in gathered[1:]):
            raise RuntimeError(f"MPI ranks selected different JIT configurations: {gathered}")

        rank_path = diagnostics / f"rank-{rank}.json"
        rank_path.write_text(
            json.dumps(selected, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        comm.Barrier()
        if rank == 0:
            (diagnostics / "summary.json").write_text(
                json.dumps(
                    {"ranks": size, "configuration": gathered[0]},
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            print(f"MPI JIT runtime configuration identical across {size} ranks")


if __name__ == "__main__":
    main()
