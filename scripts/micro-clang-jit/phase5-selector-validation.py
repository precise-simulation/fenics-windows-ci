"""Phase-5 three-backend selector, ownership, cache and functional validation."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

BACKENDS = {
    "llvm-mingw": "llvm_mingw_runtime.py",
    "tinycc": "tinycc_runtime.py",
    "micro-clang": "micro_clang_runtime.py",
}
PACKAGES = {
    "fenics-jit-runtime": "library/fenics-jit/runtime/",
    "fenics-jit-llvm-mingw": "library/fenics-jit/backends/llvm-mingw/",
    "fenics-jit-tinycc": "library/fenics-jit/backends/tinycc/",
    "fenics-jit-micro-clang": "library/fenics-jit/backends/micro-clang/",
}


def _load_selector():
    path = Path(sys.prefix) / "Library/fenics-jit/runtime/fenics_jit_selector.py"
    spec = importlib.util.spec_from_file_location("_micro_clang_phase5_selector", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load selector: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def _selector_value(value: str | None):
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


def _discover(selector, name: str):
    with _selector_value(name):
        runtime = selector.discover_runtime()
    if runtime.selected_backend != name:
        raise RuntimeError(f"selector returned {runtime.selected_backend!r}, expected {name!r}")
    return runtime


def _package_record(name: str) -> dict:
    matches = sorted((Path(sys.prefix) / "conda-meta").glob(f"{name}-*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one package record for {name}, got {matches}")
    return json.loads(matches[0].read_text(encoding="utf-8"))


def _dependency_names(record: dict) -> set[str]:
    return {
        str(item).strip().split()[0].lower()
        for item in record.get("depends", [])
        if str(item).strip()
    }


def _owned_files(record: dict) -> set[str]:
    return {str(item).replace("\\", "/").lower() for item in record.get("files", [])}


def _validate_package_ownership() -> dict[str, object]:
    records = {name: _package_record(name) for name in PACKAGES}
    files = {name: _owned_files(record) for name, record in records.items()}
    for name, root in PACKAGES.items():
        outside = sorted(path for path in files[name] if not path.startswith(root))
        if outside:
            raise RuntimeError(f"{name} owns files outside {root}: {outside}")

    overlaps = {}
    names = list(PACKAGES)
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            overlap = sorted(files[left] & files[right])
            if overlap:
                overlaps[f"{left}::{right}"] = overlap
    if overlaps:
        raise RuntimeError(f"JIT package ownership overlaps: {overlaps}")

    deps = {name: _dependency_names(record) for name, record in records.items()}
    runtime = "fenics-jit-runtime"
    backend_packages = set(PACKAGES) - {runtime}
    if deps[runtime] & backend_packages:
        raise RuntimeError(
            f"shared runtime depends on backend package(s): {deps[runtime] & backend_packages}"
        )
    for backend in backend_packages:
        if runtime not in deps[backend]:
            raise RuntimeError(f"{backend} does not depend on {runtime}")
        cross = (deps[backend] & backend_packages) - {backend}
        if cross:
            raise RuntimeError(f"{backend} depends on another backend: {cross}")

    dolfinx = _package_record("fenics-dolfinx")
    dolfinx_deps = _dependency_names(dolfinx)

    repo_root = Path(__file__).resolve().parents[2]
    dolfinx_recipe = repo_root / "recipes" / "dolfinx" / "recipe.yaml"
    recipe_text = dolfinx_recipe.read_text(encoding="utf-8")
    if "fenics-jit-llvm-mingw ==20260826" not in recipe_text:
        raise RuntimeError(
            "repository Windows fenics-dolfinx recipe no longer declares the "
            "LLVM-MinGW default backend dependency"
        )

    return {
        "status": "pass",
        "file_counts": {name: len(files[name]) for name in PACKAGES},
        "dependencies": {name: sorted(deps[name]) for name in PACKAGES},
        "pairwise_overlap": {},
        "dolfinx_recipe_backend_dependency": "fenics-jit-llvm-mingw ==20260826",
        "installed_dolfinx_dependencies": sorted(dolfinx_deps),
        "normal_install_footprint_reduction_claimed": False,
    }


def _validate_unavailable_no_fallback(selector, name: str) -> str:
    jit_root = Path(selector.__file__).resolve().parent.parent
    root = jit_root / "backends" / name
    hidden = jit_root / "backends" / f".{name}-phase5-unavailable"
    if hidden.exists():
        shutil.rmtree(hidden)
    root.rename(hidden)
    try:
        with _selector_value(name):
            try:
                selector.discover_runtime()
            except RuntimeError as exc:
                message = str(exc)
                if "backend package is unavailable" not in message or name not in message:
                    raise
            else:
                raise RuntimeError(f"unavailable {name} silently fell through to another backend")
    finally:
        hidden.rename(root)
    return "rejected-without-fallback"


def _pyds(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(str(path.relative_to(root)).replace("\\", "/") for path in root.rglob("*.pyd"))


def _compile(runtime, base_cache: Path, diagnostics: Path, scale: float) -> dict[str, object]:
    import ufl
    from dolfinx import fem, mesh
    from mpi4py import MPI

    cache = runtime.cache_root(base_cache)
    if _pyds(cache):
        raise RuntimeError(f"cache was not fresh for {runtime.selected_backend}: {cache}")
    with runtime.activate(cache_root=cache, diagnostics_dir=diagnostics):
        domain = mesh.create_unit_square(MPI.COMM_SELF, 2, 2)
        x = ufl.SpatialCoordinate(domain)
        form = fem.form((1.0 + scale * x[0]) * ufl.dx, jit_options={"cache_dir": cache})
        value = float(fem.assemble_scalar(form))
    expected = 1.0 + 0.5 * scale
    if not math.isclose(value, expected, rel_tol=2e-10, abs_tol=2e-10):
        raise RuntimeError(
            f"{runtime.selected_backend} numerical mismatch: {value} != {expected}"
        )
    modules = _pyds(cache)
    if not modules:
        raise RuntimeError(f"{runtime.selected_backend} produced no cached module")
    return {
        "backend": runtime.selected_backend,
        "cache_id": runtime.backend_cache_id,
        "cache_root": str(cache),
        "value": value,
        "modules": modules,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)

    selector = _load_selector()
    baseline = dict(os.environ)

    with _selector_value(None):
        default = selector.discover_runtime()
    if default.selected_backend != "llvm-mingw":
        raise RuntimeError(f"default backend changed unexpectedly: {default.selected_backend}")

    unavailable = {
        name: _validate_unavailable_no_fallback(selector, name)
        for name in BACKENDS
    }

    runtimes = {name: _discover(selector, name) for name in BACKENDS}
    for name, runtime in runtimes.items():
        module_name = Path(runtime.backend_module.__file__).name
        if module_name != BACKENDS[name]:
            raise RuntimeError(f"{name} loaded {module_name}, expected {BACKENDS[name]}")

    cache_ids = {name: runtime.backend_cache_id for name, runtime in runtimes.items()}
    if len(set(cache_ids.values())) != len(cache_ids):
        raise RuntimeError(f"backend cache identities are not distinct: {cache_ids}")

    base_cache = work / "logical-cache"
    physical = {
        name: runtime.cache_root(base_cache)
        for name, runtime in runtimes.items()
    }
    if len({str(path) for path in physical.values()}) != len(physical):
        raise RuntimeError(f"backend cache namespaces overlap: {physical}")
    for name, path in physical.items():
        if path.parts[-3] != "ffcx" or path.parts[-2] != name:
            raise RuntimeError(f"invalid cache namespace for {name}: {path}")

    switching = []
    for index, name in enumerate(
        ("llvm-mingw", "micro-clang", "tinycc", "micro-clang", "llvm-mingw")
    ):
        switching.append(
            _compile(
                runtimes[name],
                work / f"switch-{index}",
                work / "diagnostics" / f"{index}-{name}",
                1.0 + index,
            )
        )
        if dict(os.environ) != baseline:
            raise RuntimeError(f"environment did not restore after {name} activation")

    result = {
        "schema": 1,
        "status": "pass",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "default_backend": default.selected_backend,
        "registered_backends": list(BACKENDS),
        "module_files": {
            name: Path(runtime.backend_module.__file__).name
            for name, runtime in runtimes.items()
        },
        "unavailable_backend_behavior": unavailable,
        "cache_ids": cache_ids,
        "cache_namespaces": {name: str(path) for name, path in physical.items()},
        "package_ownership": _validate_package_ownership(),
        "switching": switching,
        "environment_restored": dict(os.environ) == baseline,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
