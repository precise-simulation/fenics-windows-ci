"""MPI child-process backend/cache propagation qualification for TinyCC Phase 4B."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path


def load_module(path: Path, name: str):
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


def load_shared_selector():
    path = Path(sys.prefix) / "Library/fenics-jit/runtime/fenics_jit_selector.py"
    if not path.is_file():
        raise RuntimeError(f"installed shared JIT selector is missing: {path}")
    return load_module(path, "phase4b_mpi_selector")


def pyd_snapshot(root: Path) -> dict[str, dict[str, object]]:
    snapshot: dict[str, dict[str, object]] = {}
    if not root.is_dir():
        return snapshot
    for path in sorted(root.rglob("*.pyd")):
        relative = str(path.relative_to(root)).replace("\\", "/")
        stat = path.stat()
        snapshot[relative] = {
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return snapshot


def find_mpiexec() -> Path:
    candidates = [
        Path(sys.prefix) / "Library/bin/mpiexec.exe",
        Path(sys.prefix) / "Scripts/mpiexec.exe",
        Path(sys.prefix) / "mpiexec.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    matches = list(Path(sys.prefix).rglob("mpiexec.exe"))
    if not matches:
        raise RuntimeError(f"mpiexec.exe not found under {sys.prefix}")
    return matches[0].resolve()


def mpi_path() -> str:
    prefix = Path(sys.prefix).resolve()
    entries = [
        prefix,
        prefix / "bin",
        prefix / "Scripts",
        prefix / "Library/bin",
    ]
    system_root = os.environ.get("SystemRoot")
    if system_root:
        entries.extend([Path(system_root) / "System32", Path(system_root)])
    return os.pathsep.join(str(path) for path in entries)


def child_probe(backend: str, work: Path, output: Path) -> int:
    import ufl
    from dolfinx import fem, mesh
    from mpi4py import MPI

    comm = MPI.COMM_WORLD
    rank = comm.rank
    size = comm.size
    if size != 2:
        raise RuntimeError(f"Task 15 qualification requires exactly 2 MPI ranks, got {size}")

    selector = load_shared_selector()
    runtime = selector.discover_runtime()
    if runtime.selected_backend != backend:
        raise RuntimeError(
            f"rank {rank}: selected backend {runtime.selected_backend!r}, expected {backend!r}"
        )

    base_cache = work / "cache"
    cache = runtime.cache_root(base_cache)
    diagnostics = work / "diag" / f"r{rank}"
    diagnostics.mkdir(parents=True, exist_ok=True)

    expected_active = {
        "FENICS_JIT_COMPILER": backend,
        "FENICS_JIT_BACKEND_CACHE_ID": runtime.backend_cache_id,
        "FENICS_JIT_CACHE_ROOT": str(cache.resolve()),
        "FENICS_JIT_BACKEND_ROOT": str(runtime.backend_root.resolve()),
    }

    with runtime.activate(cache_root=cache, diagnostics_dir=diagnostics):
        active = {key: os.environ.get(key) for key in expected_active}
        if active != expected_active:
            raise RuntimeError(
                f"rank {rank}: active JIT identity mismatch: "
                f"expected={expected_active!r}, actual={active!r}"
            )

        domain = mesh.create_unit_square(comm, 2, 2)
        x = ufl.SpatialCoordinate(domain)
        scale = 1.75 if backend == "tinycc" else 1.25
        form = fem.form(
            (1.0 + scale * x[0]) * ufl.dx,
            jit_options={"cache_dir": cache},
        )
        local_value = float(fem.assemble_scalar(form))
        value = float(comm.allreduce(local_value, op=MPI.SUM))

        record_path = diagnostics / "shared-runtime.json"
        if not record_path.is_file():
            raise RuntimeError(f"rank {rank}: shared runtime diagnostics missing")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        expected_record = {
            "selected_backend": backend,
            "backend_cache_id": runtime.backend_cache_id,
            "backend_root": str(runtime.backend_root.resolve()),
            "cache_root": str(cache.resolve()),
            "activation_depth": 1,
        }
        actual_record = {key: record.get(key) for key in expected_record}
        if actual_record != expected_record:
            raise RuntimeError(
                f"rank {rank}: shared diagnostics mismatch: "
                f"expected={expected_record!r}, actual={actual_record!r}"
            )

    expected_value = 1.0 + 0.5 * scale
    if not math.isclose(value, expected_value, rel_tol=2e-10, abs_tol=2e-10):
        raise RuntimeError(
            f"rank {rank}: MPI JIT numerical mismatch: got {value}, expected {expected_value}"
        )

    comm.barrier()
    modules = pyd_snapshot(cache)
    if not modules:
        raise RuntimeError(f"rank {rank}: MPI JIT did not produce a cached .pyd")

    rank_record = {
        "rank": rank,
        "size": size,
        "backend": backend,
        "backend_cache_id": runtime.backend_cache_id,
        "backend_root": str(runtime.backend_root.resolve()),
        "cache_root": str(cache.resolve()),
        "value": value,
        "modules": modules,
        "diagnostics": record,
    }
    gathered = comm.gather(rank_record, root=0)

    if rank == 0:
        assert gathered is not None
        cache_ids = {item["backend_cache_id"] for item in gathered}
        cache_roots = {item["cache_root"] for item in gathered}
        backend_roots = {item["backend_root"] for item in gathered}
        module_sets = {json.dumps(item["modules"], sort_keys=True) for item in gathered}
        if len(cache_ids) != 1:
            raise RuntimeError(f"MPI ranks disagreed on backend cache identity: {cache_ids!r}")
        if len(cache_roots) != 1:
            raise RuntimeError(f"MPI ranks disagreed on physical cache root: {cache_roots!r}")
        if len(backend_roots) != 1:
            raise RuntimeError(f"MPI ranks disagreed on backend root: {backend_roots!r}")
        if len(module_sets) != 1:
            raise RuntimeError("MPI ranks observed different cached module snapshots")

        result = {
            "status": "pass",
            "backend": backend,
            "ranks": gathered,
            "shared_backend_cache_id": next(iter(cache_ids)),
            "shared_cache_root": next(iter(cache_roots)),
            "shared_backend_root": next(iter(backend_roots)),
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    comm.barrier()
    return 0


def parent_probe(work: Path, output: Path) -> int:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    mpiexec = find_mpiexec()
    python_path = Path(sys.prefix) / "Lib/site-packages"
    results: list[dict[str, object]] = []

    for backend, tag in (("llvm-mingw", "ll"), ("tinycc", "tt")):
        backend_work = work / tag
        backend_output = work / f"{tag}.json"
        command = [
            str(mpiexec),
            "-localonly",
            "-n",
            "2",
            "-env",
            "PATH",
            mpi_path(),
            "-env",
            "PYTHONPATH",
            str(python_path),
            "-env",
            "FENICS_JIT_COMPILER",
            backend,
            sys.executable,
            str(Path(__file__).resolve()),
            "--child",
            "--backend",
            backend,
            "--work-dir",
            str(backend_work),
            "--output",
            str(backend_output),
        ]
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            raise RuntimeError(
                f"{backend} MPI propagation qualification failed with "
                f"exit code {completed.returncode}"
            )
        if not backend_output.is_file():
            raise RuntimeError(f"{backend} MPI evidence file was not created")
        result = json.loads(backend_output.read_text(encoding="utf-8"))
        if result.get("status") != "pass":
            raise RuntimeError(f"{backend} MPI evidence did not pass: {result!r}")
        results.append(result)

    aggregate = {
        "status": "pass",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "rank_count": 2,
        "backends": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(aggregate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(aggregate, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", choices=("llvm-mingw", "tinycc"))
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()

    work = args.work_dir.resolve()
    output = args.output.resolve()

    if args.child:
        if args.backend is None:
            raise RuntimeError("--child requires --backend")
        return child_probe(args.backend, work, output)
    if args.backend is not None:
        raise RuntimeError("--backend is only valid with --child")
    return parent_probe(work, output)


if __name__ == "__main__":
    raise SystemExit(main())
