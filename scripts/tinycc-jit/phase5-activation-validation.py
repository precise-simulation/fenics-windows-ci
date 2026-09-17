"""Real installed-backend activation/lifecycle validation for TinyCC Phase 5."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import threading
from pathlib import Path
from types import ModuleType

from cffi import FFI
from cffi import _shimmed_dist_utils as _dist


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


def _load_selector() -> ModuleType:
    path = Path(sys.prefix) / "Library" / "fenics-jit" / "runtime" / "fenics_jit_selector.py"
    if not path.is_file():
        raise RuntimeError(f"installed shared JIT selector is missing: {path}")
    return _load_module(path, "_tinycc_phase5_activation_selector")


def _discover(selector: ModuleType, backend: str):
    had = "FENICS_JIT_COMPILER" in os.environ
    old = os.environ.get("FENICS_JIT_COMPILER")
    os.environ["FENICS_JIT_COMPILER"] = backend
    try:
        runtime = selector.discover_runtime()
    finally:
        if had:
            assert old is not None
            os.environ["FENICS_JIT_COMPILER"] = old
        else:
            os.environ.pop("FENICS_JIT_COMPILER", None)
    if runtime.selected_backend != backend:
        raise RuntimeError(
            f"shared selector returned {runtime.selected_backend!r}, expected {backend!r}"
        )
    return runtime


def _assert_idle(
    selector: ModuleType,
    baseline_environment: dict[str, str],
    original_distribution: object,
) -> None:
    if selector._ACTIVE_BACKEND is not None:
        raise RuntimeError(f"shared runtime backend remained active: {selector._ACTIVE_BACKEND}")
    if selector._ACTIVE_OWNER_THREAD is not None:
        raise RuntimeError(
            f"shared runtime owner remained active: {selector._ACTIVE_OWNER_THREAD}"
        )
    if selector._ACTIVE_DEPTH != 0:
        raise RuntimeError(f"shared runtime depth did not restore: {selector._ACTIVE_DEPTH}")
    if dict(os.environ) != baseline_environment:
        raise RuntimeError("process environment did not restore after activation validation")
    if _dist.Distribution is not original_distribution:
        raise RuntimeError("CFFI Distribution interception was not restored")


def _pyds(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(str(path.relative_to(root)).replace("\\", "/") for path in root.rglob("*.pyd"))


def _fresh_ffcx_compile(runtime, *, base_cache: Path, diagnostics: Path, scale: float) -> dict[str, object]:
    import ufl
    from dolfinx import fem, mesh
    from mpi4py import MPI

    cache = runtime.cache_root(base_cache)
    if _pyds(cache):
        raise RuntimeError(f"{runtime.selected_backend} activation cache was not fresh: {cache}")

    with runtime.activate(cache_root=cache, diagnostics_dir=diagnostics):
        if os.environ.get("FENICS_JIT_COMPILER") != runtime.selected_backend:
            raise RuntimeError("selected backend was not active before FFCx form creation")
        if os.environ.get("FENICS_JIT_CACHE_ROOT") != str(cache.resolve()):
            raise RuntimeError("backend cache root was not active before FFCx form creation")
        domain = mesh.create_unit_square(MPI.COMM_SELF, 2, 2)
        x = ufl.SpatialCoordinate(domain)
        form = fem.form(
            (1.0 + scale * x[0]) * ufl.dx,
            jit_options={"cache_dir": cache},
        )
        value = float(fem.assemble_scalar(form))

    expected = 1.0 + 0.5 * scale
    if not math.isclose(value, expected, rel_tol=2e-10, abs_tol=2e-10):
        raise RuntimeError(
            f"{runtime.selected_backend} activation numerical mismatch: "
            f"got {value}, expected {expected}"
        )
    modules = _pyds(cache)
    if not modules:
        raise RuntimeError(f"{runtime.selected_backend} activation produced no JIT module")
    return {
        "backend": runtime.selected_backend,
        "backend_cache_id": runtime.backend_cache_id,
        "cache_root": str(cache),
        "value": value,
        "generated_modules": modules,
        "activation_preceded_form_creation": True,
    }


def _same_backend_nesting(
    selector: ModuleType,
    runtime,
    *,
    root: Path,
    baseline_environment: dict[str, str],
) -> dict[str, object]:
    outer_cache = runtime.cache_root(root / "outer")
    inner_cache = runtime.cache_root(root / "inner")
    with runtime.activate(cache_root=outer_cache, diagnostics_dir=root / "diag-outer"):
        if selector._ACTIVE_BACKEND != runtime.selected_backend or selector._ACTIVE_DEPTH != 1:
            raise RuntimeError("same-backend outer activation identity mismatch")
        outer_environment = dict(os.environ)
        with runtime.activate(cache_root=inner_cache, diagnostics_dir=root / "diag-inner"):
            if selector._ACTIVE_BACKEND != runtime.selected_backend or selector._ACTIVE_DEPTH != 2:
                raise RuntimeError("same-backend nested activation did not reach depth 2")
        if selector._ACTIVE_DEPTH != 1:
            raise RuntimeError("same-backend nesting did not restore outer depth")
        if dict(os.environ) != outer_environment:
            raise RuntimeError("same-backend nesting did not restore outer environment")
    if dict(os.environ) != baseline_environment:
        raise RuntimeError("same-backend nesting did not restore baseline environment")
    return {
        "status": "pass",
        "backend": runtime.selected_backend,
        "outer_cache": str(outer_cache),
        "inner_cache": str(inner_cache),
        "max_activation_depth": 2,
    }


def _conflicting_nesting(
    selector: ModuleType,
    outer,
    inner,
    *,
    root: Path,
    baseline_environment: dict[str, str],
) -> dict[str, object]:
    outer_cache = outer.cache_root(root / "outer")
    inner_cache = inner.cache_root(root / "inner")
    with outer.activate(cache_root=outer_cache, diagnostics_dir=root / "diag-outer"):
        outer_environment = dict(os.environ)
        try:
            with inner.activate(cache_root=inner_cache, diagnostics_dir=root / "diag-inner"):
                raise AssertionError("conflicting backend activation unexpectedly entered")
        except RuntimeError as exc:
            message = str(exc)
            if "Conflicting nested FEniCS JIT activation" not in message:
                raise
        else:
            raise RuntimeError("conflicting nested backend activation was accepted")
        if selector._ACTIVE_BACKEND != outer.selected_backend or selector._ACTIVE_DEPTH != 1:
            raise RuntimeError("conflicting activation altered the outer lifecycle identity")
        if dict(os.environ) != outer_environment:
            raise RuntimeError("conflicting activation altered the outer environment")
    if dict(os.environ) != baseline_environment:
        raise RuntimeError("conflicting activation did not restore baseline environment")
    return {
        "status": "pass",
        "outer_backend": outer.selected_backend,
        "rejected_backend": inner.selected_backend,
        "error_contains": "Conflicting nested FEniCS JIT activation",
    }


def _failure_restoration(
    selector: ModuleType,
    tinycc,
    *,
    root: Path,
    baseline_environment: dict[str, str],
    original_distribution: object,
) -> dict[str, object]:
    failure_cache = tinycc.cache_root(root / "failure-cache")
    failure_dir = root / "failure-build"
    ffi = FFI()
    ffi.cdef("int phase5_failure_probe(void);")
    ffi.set_source(
        "_tinycc_phase5_expected_failure",
        "int phase5_failure_probe(void) { this is intentionally invalid C; }\n",
    )

    failure_type: str | None = None
    try:
        with tinycc.activate(
            cache_root=failure_cache,
            diagnostics_dir=root / "failure-diagnostics",
        ):
            ffi.compile(tmpdir=str(failure_dir), verbose=False)
    except BaseException as exc:
        failure_type = type(exc).__name__
    else:
        raise RuntimeError("intentional TinyCC compilation failure unexpectedly succeeded")

    _assert_idle(selector, baseline_environment, original_distribution)
    recovery = _fresh_ffcx_compile(
        tinycc,
        base_cache=root / "recovery-cache",
        diagnostics=root / "recovery-diagnostics",
        scale=3.25,
    )
    _assert_idle(selector, baseline_environment, original_distribution)
    return {
        "status": "pass",
        "failure_type": failure_type,
        "state_restored_after_failure": True,
        "successful_jit_after_failure": recovery,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if os.environ.get("PYTHONHASHSEED") != "0":
        raise RuntimeError("TinyCC Phase-5 activation validation requires PYTHONHASHSEED=0")

    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    selector = _load_selector()
    llvm = _discover(selector, "llvm-mingw")
    tinycc = _discover(selector, "tinycc")
    baseline_environment = dict(os.environ)
    original_distribution = _dist.Distribution

    nesting = _same_backend_nesting(
        selector,
        tinycc,
        root=work / "same-backend-nesting",
        baseline_environment=baseline_environment,
    )
    _assert_idle(selector, baseline_environment, original_distribution)

    conflict = _conflicting_nesting(
        selector,
        llvm,
        tinycc,
        root=work / "conflicting-nesting",
        baseline_environment=baseline_environment,
    )
    _assert_idle(selector, baseline_environment, original_distribution)

    switching = [
        _fresh_ffcx_compile(
            llvm,
            base_cache=work / "switch-llvm-first",
            diagnostics=work / "switch-diagnostics" / "llvm-first",
            scale=1.5,
        ),
        _fresh_ffcx_compile(
            tinycc,
            base_cache=work / "switch-tinycc",
            diagnostics=work / "switch-diagnostics" / "tinycc",
            scale=2.5,
        ),
        _fresh_ffcx_compile(
            llvm,
            base_cache=work / "switch-llvm-second",
            diagnostics=work / "switch-diagnostics" / "llvm-second",
            scale=3.5,
        ),
    ]
    _assert_idle(selector, baseline_environment, original_distribution)
    cache_roots = [item["cache_root"] for item in switching]
    if len(set(cache_roots)) != len(cache_roots):
        raise RuntimeError(f"backend switching reused a physical cache root: {cache_roots!r}")

    failure = _failure_restoration(
        selector,
        tinycc,
        root=work / "failure-restoration",
        baseline_environment=baseline_environment,
        original_distribution=original_distribution,
    )

    result = {
        "schema": 1,
        "kind": "tinycc-phase5-activation-validation",
        "status": "pass",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "python_hash_seed": os.environ["PYTHONHASHSEED"],
        "same_thread_same_backend_nesting": nesting,
        "conflicting_same_thread_backend_nesting": conflict,
        "sequential_backend_switching": {
            "status": "pass",
            "sequence": ["llvm-mingw", "tinycc", "llvm-mingw"],
            "fresh_compilations": switching,
            "distinct_physical_cache_roots": True,
        },
        "compilation_failure_restoration": failure,
        "lifecycle": {
            "final_backend": selector._ACTIVE_BACKEND,
            "final_owner_thread": selector._ACTIVE_OWNER_THREAD,
            "final_depth": selector._ACTIVE_DEPTH,
            "environment_restored": dict(os.environ) == baseline_environment,
            "cffi_distribution_restored": _dist.Distribution is original_distribution,
            "main_thread": threading.get_ident(),
        },
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "TinyCC Phase 5 activation validation passed: nesting, conflict rejection, "
        "LLVM-MinGW -> TinyCC -> LLVM-MinGW switching, failure restoration"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
