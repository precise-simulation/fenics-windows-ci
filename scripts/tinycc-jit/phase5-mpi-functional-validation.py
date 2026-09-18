"""Run the established two-rank Phase-5 FFCx MPI corpus under TinyCC."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path
from types import ModuleType


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _run_child(cache_dir: Path, diagnostics: Path) -> int:
    scripts = Path(__file__).resolve().parent
    tinycc = _load_module(
        scripts / "phase5-functional-validation.py",
        "_tinycc_phase5_mpi_backend",
    )

    os.environ["FENICS_JIT_COMPILER"] = "tinycc"
    selector = tinycc._load_selector()
    runtime = selector.discover_runtime()
    if runtime.selected_backend != "tinycc":
        raise RuntimeError(f"FENICS_JIT_COMPILER=tinycc selected {runtime.selected_backend!r}")

    physical_cache = runtime.cache_root(cache_dir.resolve())
    tinycc._ACTIVE_RUNTIME = runtime
    tinycc._ACTIVE_CACHE_ROOT = physical_cache

    validator = tinycc._load_reference_validator()
    validator._runtime_record = tinycc._runtime_record
    validator._record_check_calls = tinycc._record_tinycc_runs
    validator._assert_compiler_commands = tinycc._assert_tinycc_commands
    validator._inspect_pyds = tinycc._inspect_tinycc_pyds
    try:
        validator._mpi_validation(physical_cache, diagnostics.resolve())
    except BaseException:
        traceback.print_exc()
        sys.stderr.flush()
        from mpi4py import MPI

        try:
            MPI.COMM_WORLD.Abort(1)
        finally:
            os._exit(1)
    return 0


def _run_parent(cache_dir: Path, diagnostics: Path) -> int:
    scripts = Path(__file__).resolve().parent
    helper = _load_module(scripts / "phase4b-mpi-proof.py", "_tinycc_phase5_mpi_helper")
    mpiexec = helper.find_mpiexec()
    python_path = Path(sys.prefix).resolve() / "Lib/site-packages"
    diagnostics = diagnostics.resolve()
    diagnostics.mkdir(parents=True, exist_ok=True)

    command = [
        str(mpiexec),
        "-localonly",
        "-n",
        "2",
        "-env",
        "PATH",
        helper.mpi_path(),
        "-env",
        "PYTHONPATH",
        str(python_path),
        "-env",
        "FENICS_JIT_COMPILER",
        "tinycc",
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        "--cache-dir",
        str(cache_dir.resolve()),
        "--diagnostics-dir",
        str(diagnostics),
    ]
    (diagnostics / "mpi-launch-command.txt").write_text(
        subprocess.list2cmdline(command) + "\n",
        encoding="utf-8",
    )
    try:
        completed = subprocess.run(
            command,
            check=False,
            timeout=helper.MPI_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "TinyCC Phase-5 MPI functional validation exceeded "
            f"{helper.MPI_TIMEOUT_SECONDS} seconds"
        ) from exc
    if completed.returncode != 0:
        raise RuntimeError(
            "TinyCC Phase-5 MPI functional validation failed with "
            f"exit code {completed.returncode}"
        )

    summary_path = diagnostics / "mpi-summary.json"
    if not summary_path.is_file():
        raise RuntimeError("TinyCC Phase-5 MPI summary was not produced")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("mode") != "mpi" or summary.get("ranks") != 2:
        raise RuntimeError(f"unexpected TinyCC Phase-5 MPI summary: {summary!r}")
    if summary.get("compile_commands_by_rank") != [1, 0]:
        raise RuntimeError(f"unexpected TinyCC MPI compile ownership: {summary!r}")

    print("TinyCC Phase 5 integrated two-rank MPI functional validation passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--diagnostics-dir", type=Path, required=True)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        return _run_child(args.cache_dir, args.diagnostics_dir)
    return _run_parent(args.cache_dir, args.diagnostics_dir)


if __name__ == "__main__":
    raise SystemExit(main())
