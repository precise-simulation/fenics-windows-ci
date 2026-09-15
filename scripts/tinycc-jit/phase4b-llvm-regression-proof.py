"""Default-vs-explicit LLVM-MinGW regression qualification for TinyCC Phase 4B."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
from contextlib import contextmanager
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
    return load_module(path, "phase4b_llvm_regression_selector")


@contextmanager
def selector_value(value: str | None):
    had = "FENICS_JIT_COMPILER" in os.environ
    old = os.environ.get("FENICS_JIT_COMPILER")
    if value is None:
        os.environ.pop("FENICS_JIT_COMPILER", None)
    else:
        os.environ["FENICS_JIT_COMPILER"] = value
    try:
        yield
    finally:
        if had:
            assert old is not None
            os.environ["FENICS_JIT_COMPILER"] = old
        else:
            os.environ.pop("FENICS_JIT_COMPILER", None)


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


def compile_form_with_shared(runtime, cache: Path, diagnostics: Path) -> float:
    import ufl
    from dolfinx import fem, mesh
    from mpi4py import MPI

    with runtime.activate(cache_root=cache, diagnostics_dir=diagnostics):
        domain = mesh.create_unit_square(MPI.COMM_SELF, 3, 2)
        x = ufl.SpatialCoordinate(domain)
        form = fem.form(
            (1.0 + 1.5 * x[0] + 0.5 * x[1]) * ufl.dx,
            jit_options={"cache_dir": cache},
        )
        return float(fem.assemble_scalar(form))


def compile_form_with_direct(config, cache: Path, diagnostics: Path) -> float:
    import ufl
    from dolfinx import fem, mesh
    from mpi4py import MPI

    with config.activate(diagnostics_dir=diagnostics):
        domain = mesh.create_unit_square(MPI.COMM_SELF, 3, 2)
        x = ufl.SpatialCoordinate(domain)
        form = fem.form(
            (1.0 + 1.5 * x[0] + 0.5 * x[1]) * ufl.dx,
            jit_options={"cache_dir": cache},
        )
        return float(fem.assemble_scalar(form))


def assert_value(label: str, value: float) -> None:
    expected = 2.0
    if not math.isclose(value, expected, rel_tol=2e-10, abs_tol=2e-10):
        raise RuntimeError(f"{label} numerical mismatch: got {value}, expected {expected}")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    work = args.work_dir.resolve()
    output = args.output.resolve()
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    baseline = dict(os.environ)
    selector = load_shared_selector()

    with selector_value(None):
        default_runtime = selector.discover_runtime()
    if default_runtime.selected_backend != "llvm-mingw":
        raise RuntimeError(
            "unset FENICS_JIT_COMPILER did not select LLVM-MinGW: "
            f"{default_runtime.selected_backend!r}"
        )

    with selector_value("llvm-mingw"):
        explicit_runtime = selector.discover_runtime()

    if explicit_runtime.selected_backend != "llvm-mingw":
        raise RuntimeError(
            "explicit FENICS_JIT_COMPILER=llvm-mingw did not select LLVM-MinGW"
        )
    if explicit_runtime.backend_cache_id != default_runtime.backend_cache_id:
        raise RuntimeError(
            "default and explicit LLVM-MinGW cache identities differ: "
            f"default={default_runtime.backend_cache_id}, "
            f"explicit={explicit_runtime.backend_cache_id}"
        )
    if explicit_runtime.backend_root.resolve() != default_runtime.backend_root.resolve():
        raise RuntimeError(
            "default and explicit LLVM-MinGW backend roots differ: "
            f"default={default_runtime.backend_root}, explicit={explicit_runtime.backend_root}"
        )

    base_cache = work / "cache"
    default_cache = default_runtime.cache_root(base_cache)
    explicit_cache = explicit_runtime.cache_root(base_cache)
    if explicit_cache != default_cache:
        raise RuntimeError(
            "default and explicit LLVM-MinGW physical cache roots differ: "
            f"default={default_cache}, explicit={explicit_cache}"
        )

    default_value = compile_form_with_shared(
        default_runtime,
        default_cache,
        work / "diag-default",
    )
    assert_value("default shared LLVM-MinGW", default_value)
    default_modules = pyd_snapshot(default_cache)
    if not default_modules:
        raise RuntimeError("default shared LLVM-MinGW JIT did not produce a cached .pyd")

    explicit_value = compile_form_with_shared(
        explicit_runtime,
        explicit_cache,
        work / "diag-explicit",
    )
    assert_value("explicit shared LLVM-MinGW", explicit_value)
    explicit_modules = pyd_snapshot(explicit_cache)
    if explicit_modules != default_modules:
        raise RuntimeError(
            "explicit LLVM-MinGW selector did not reuse the default selector cache unchanged"
        )

    direct_runtime = load_module(
        default_runtime.backend_root / "fenics_jit_runtime.py",
        "phase4b_llvm_regression_direct_runtime",
    )
    direct_config = direct_runtime.RuntimeConfig.discover(
        toolchain_root=default_runtime.backend_root,
        python_prefix=Path(sys.prefix),
    )
    direct_record = direct_config.diagnostic_record()
    shared_record = default_runtime.diagnostic_record(default_cache)
    backend_record = shared_record.get("backend")
    if not isinstance(backend_record, dict):
        raise RuntimeError("shared LLVM-MinGW diagnostics do not contain a backend record")

    mismatches = {
        key: {"direct": value, "shared": backend_record.get(key)}
        for key, value in direct_record.items()
        if backend_record.get(key) != value
    }
    if mismatches:
        raise RuntimeError(
            "shared LLVM-MinGW runtime configuration changed from the direct runtime: "
            f"{mismatches!r}"
        )

    direct_cache = work / "direct-cache"
    direct_value = compile_form_with_direct(
        direct_config,
        direct_cache,
        work / "diag-direct",
    )
    assert_value("direct LLVM-MinGW runtime", direct_value)
    direct_modules = pyd_snapshot(direct_cache)
    if not direct_modules:
        raise RuntimeError("direct LLVM-MinGW runtime JIT did not produce a cached .pyd")

    default_names = {Path(path).name for path in default_modules}
    direct_names = {Path(path).name for path in direct_modules}
    common_names = sorted(default_names & direct_names)
    if not common_names:
        raise RuntimeError(
            "shared default and direct LLVM-MinGW runtime did not compile a common FFCx module"
        )

    if dict(os.environ) != baseline:
        raise RuntimeError("LLVM-MinGW regression qualification did not restore the environment")

    result = {
        "status": "pass",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "default_selector": {
            "selected_backend": default_runtime.selected_backend,
            "backend_cache_id": default_runtime.backend_cache_id,
            "backend_root": str(default_runtime.backend_root.resolve()),
            "cache_root": str(default_cache),
            "value": default_value,
            "modules": default_modules,
        },
        "explicit_selector": {
            "selected_backend": explicit_runtime.selected_backend,
            "backend_cache_id": explicit_runtime.backend_cache_id,
            "backend_root": str(explicit_runtime.backend_root.resolve()),
            "cache_root": str(explicit_cache),
            "value": explicit_value,
            "cache_reuse_unchanged": True,
        },
        "direct_runtime": {
            "value": direct_value,
            "cache_root": str(direct_cache),
            "modules": direct_modules,
            "diagnostics": direct_record,
        },
        "shared_backend_diagnostics_match_direct_runtime": True,
        "common_module_names": common_names,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
