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
import sysconfig
from pathlib import Path

LLVM_WINDOWS_ABI_POLICY = "x86_64-w64-mingw32-ms-bitfields-longdouble80-storage16-v1"
COMMON_EXTERNAL_CONFIG_POLICY = "suppress-all-v1"
COMMON_SYSTEM_LIBRARY_POLICY = "windows-system-dll-resolution-v1"
LLVM_CRT_IDENTITY = "ucrt-v1"


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


def require_string(mapping: dict[str, object], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{label} does not contain non-empty {key}")
    return value.strip()


def dynamic_include_identity(runtime, backend_record: dict[str, object]) -> dict[str, object]:
    if runtime.selected_backend == "llvm-mingw":
        raw_roots = backend_record.get("include_roots")
        if not isinstance(raw_roots, dict):
            raise RuntimeError("LLVM-MinGW diagnostics do not contain include_roots")
        include_roots = {
            key: require_string(raw_roots, key, "LLVM-MinGW include_roots")
            for key in ("python", "ffcx", "toolchain")
        }
        python_abi_definition = require_string(
            backend_record, "python_abi_definition", "LLVM-MinGW diagnostics"
        )
    else:
        python_include = Path(sysconfig.get_path("include") or "").resolve()
        spec = importlib.util.find_spec("ffcx")
        if spec is None or not spec.submodule_search_locations:
            raise RuntimeError("TinyCC MPI diagnostics cannot locate installed FFCx")
        ffcx_root = Path(next(iter(spec.submodule_search_locations))).resolve()
        include_roots = {
            "python": str(python_include),
            "ffcx": str((ffcx_root / "codegeneration").resolve()),
            "toolchain": str((runtime.backend_root / "include").resolve()),
        }
        python_abi_definition = require_string(
            backend_record, "python_abi_definition", "TinyCC diagnostics"
        )

    for key, raw_path in include_roots.items():
        path = Path(raw_path)
        if not path.is_dir():
            raise RuntimeError(
                f"{runtime.selected_backend} diagnostics include root {key} is missing: {path}"
            )
    abi_path = Path(python_abi_definition)
    if not abi_path.is_file():
        raise RuntimeError(
            f"{runtime.selected_backend} Python ABI definition is missing: {abi_path}"
        )
    return {
        "python_abi_definition": str(abi_path.resolve()),
        "include_roots": {key: str(Path(value).resolve()) for key, value in include_roots.items()},
    }


def assert_required_backend_diagnostics(
    runtime,
    record: dict[str, object],
    rank: int,
) -> dict[str, object]:
    backend_record = record.get("backend")
    if not isinstance(backend_record, dict):
        raise RuntimeError(f"rank {rank}: shared diagnostics do not contain backend record")

    if runtime.selected_backend == "tinycc":
        policy = runtime.metadata.get("policy")
        if not isinstance(policy, dict):
            raise RuntimeError(f"rank {rank}: TinyCC metadata does not contain policy")
        expected = {
            "adapter": "tinycc-direct-cffi",
            "backend_cache_id": runtime.backend_cache_id,
            "compiler_revision": require_string(
                runtime.metadata, "source_revision", "TinyCC metadata"
            ),
            "windows_abi_policy": require_string(policy, "abi", "TinyCC policy"),
            "external_config_policy": require_string(
                policy, "external_config", "TinyCC policy"
            ),
            "system_library_policy": require_string(
                policy, "system_library", "TinyCC policy"
            ),
            "crt_identity": require_string(policy, "crt", "TinyCC policy"),
        }
    else:
        release = require_string(runtime.metadata, "llvm_mingw_release", "LLVM-MinGW metadata")
        archive_sha256 = require_string(
            runtime.metadata, "upstream_sha256", "LLVM-MinGW metadata"
        )
        expected = {
            "adapter": "llvm-mingw-cffi-runtime",
            "backend_cache_id": runtime.backend_cache_id,
            "compiler_revision": f"llvm-mingw-{release}-sha256-{archive_sha256}",
            "windows_abi_policy": LLVM_WINDOWS_ABI_POLICY,
            "external_config_policy": COMMON_EXTERNAL_CONFIG_POLICY,
            "system_library_policy": COMMON_SYSTEM_LIBRARY_POLICY,
            "crt_identity": LLVM_CRT_IDENTITY,
        }

    actual = {key: backend_record.get(key) for key in expected}
    if actual != expected:
        raise RuntimeError(
            f"rank {rank}: {runtime.selected_backend} backend diagnostics mismatch: "
            f"expected={expected!r}, actual={actual!r}"
        )

    abi_policy = str(actual["windows_abi_policy"]).lower()
    for required in ("bitfields", "longdouble"):
        if required not in abi_policy:
            raise RuntimeError(
                f"rank {rank}: {runtime.selected_backend} ABI policy does not expose {required}: "
                f"{actual['windows_abi_policy']!r}"
            )

    include_identity = dynamic_include_identity(runtime, backend_record)
    return {**actual, **include_identity}


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
        required_diagnostics = assert_required_backend_diagnostics(runtime, record, rank)

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
        "required_backend_diagnostics": required_diagnostics,
        "diagnostics": record,
    }
    gathered = comm.gather(rank_record, root=0)

    if rank == 0:
        assert gathered is not None
        cache_ids = {item["backend_cache_id"] for item in gathered}
        cache_roots = {item["cache_root"] for item in gathered}
        backend_roots = {item["backend_root"] for item in gathered}
        module_sets = {json.dumps(item["modules"], sort_keys=True) for item in gathered}
        diagnostic_sets = {
            json.dumps(item["required_backend_diagnostics"], sort_keys=True)
            for item in gathered
        }
        if len(cache_ids) != 1:
            raise RuntimeError(f"MPI ranks disagreed on backend cache identity: {cache_ids!r}")
        if len(cache_roots) != 1:
            raise RuntimeError(f"MPI ranks disagreed on physical cache root: {cache_roots!r}")
        if len(backend_roots) != 1:
            raise RuntimeError(f"MPI ranks disagreed on backend root: {backend_roots!r}")
        if len(module_sets) != 1:
            raise RuntimeError("MPI ranks observed different cached module snapshots")
        if len(diagnostic_sets) != 1:
            raise RuntimeError(
                "MPI ranks disagreed on compiler/policy/include diagnostic identity"
            )

        result = {
            "status": "pass",
            "backend": backend,
            "ranks": gathered,
            "shared_backend_cache_id": next(iter(cache_ids)),
            "shared_cache_root": next(iter(cache_roots)),
            "shared_backend_root": next(iter(backend_roots)),
            "shared_required_backend_diagnostics": gathered[0][
                "required_backend_diagnostics"
            ],
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
