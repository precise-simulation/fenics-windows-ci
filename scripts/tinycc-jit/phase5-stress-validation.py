"""Integrated repeatability stress validation for TinyCC Phase 5."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from types import ModuleType

from cffi import FFI
from cffi import _shimmed_dist_utils as _dist

_CFFI_CYCLES = 100
_FFCX_CYCLES = 20


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
    return _load_module(path, "_tinycc_phase5_stress_selector")


def _discover_tinycc(selector: ModuleType):
    had = "FENICS_JIT_COMPILER" in os.environ
    old = os.environ.get("FENICS_JIT_COMPILER")
    os.environ["FENICS_JIT_COMPILER"] = "tinycc"
    try:
        runtime = selector.discover_runtime()
    finally:
        if had:
            assert old is not None
            os.environ["FENICS_JIT_COMPILER"] = old
        else:
            os.environ.pop("FENICS_JIT_COMPILER", None)
    if runtime.selected_backend != "tinycc":
        raise RuntimeError(f"shared selector returned {runtime.selected_backend!r}, expected 'tinycc'")
    return runtime


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compiler_records(diagnostics: Path) -> list[dict[str, object]]:
    path = diagnostics / "compiler-commands.jsonl"
    if not path.is_file():
        return []
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict):
            raise RuntimeError(f"invalid compiler record in {path}: {record!r}")
        records.append(record)
    return records


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
        raise RuntimeError("process environment did not restore after TinyCC stress activation")
    if _dist.Distribution is not original_distribution:
        raise RuntimeError("CFFI Distribution interception was not restored after activation")


def _cffi_stress(
    selector: ModuleType,
    runtime,
    *,
    work: Path,
    temporary_root: Path,
    baseline_environment: dict[str, str],
    original_distribution: object,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    activation_cache = runtime.cache_root(temporary_root / "cffi activation cache")
    diagnostics = work / "diagnostics" / "cffi"
    for index in range(_CFFI_CYCLES):
        name = f"_tinycc_phase5_stress_cffi_{index:03d}"
        function = f"phase5_stress_value_{index:03d}"
        expected = index + 17
        build = temporary_root / "cffi builds" / f"{index:03d}"
        before_records = len(_compiler_records(diagnostics))

        ffi = FFI()
        ffi.cdef(f"int {function}(void);")
        ffi.set_source(
            name,
            f"int {function}(void) {{ return {expected}; }}\n",
        )
        with runtime.activate(
            cache_root=activation_cache,
            diagnostics_dir=diagnostics,
        ):
            output = Path(ffi.compile(tmpdir=str(build), verbose=False)).resolve()
            module = _load_module(output, name)
            value = int(getattr(module.lib, function)())

        if value != expected:
            raise RuntimeError(
                f"CFFI stress cycle {index} returned {value}, expected {expected}"
            )
        records = _compiler_records(diagnostics)
        cycle_records = records[before_records:]
        if not cycle_records:
            raise RuntimeError(f"CFFI stress cycle {index} recorded no TinyCC command")
        sources = sorted(build.rglob("*.c"))
        if not sources:
            raise RuntimeError(f"CFFI stress cycle {index} generated no C source")
        _assert_idle(selector, baseline_environment, original_distribution)
        results.append(
            {
                "index": index,
                "module": name,
                "value": value,
                "compiler_command_count": len(cycle_records),
                "generated_source_sha256": [_sha256(path) for path in sources],
                "output_sha256": _sha256(output),
            }
        )
    return results


def _ffcx_stress(
    selector: ModuleType,
    runtime,
    *,
    work: Path,
    temporary_root: Path,
    baseline_environment: dict[str, str],
    original_distribution: object,
) -> list[dict[str, object]]:
    import ufl
    from dolfinx import fem, mesh
    from mpi4py import MPI

    domain = mesh.create_unit_square(MPI.COMM_SELF, 3, 3)
    x = ufl.SpatialCoordinate(domain)
    seen_module_names: set[str] = set()
    results: list[dict[str, object]] = []
    diagnostics = work / "diagnostics" / "ffcx"

    for index in range(_FFCX_CYCLES):
        power = index + 1
        term = x[0]
        for _ in range(1, power):
            term = term * x[0]

        base_cache = temporary_root / "ffcx caches" / f"{index:03d}"
        cache = runtime.cache_root(base_cache)
        before_records = len(_compiler_records(diagnostics))
        if cache.exists() and any(cache.rglob("*.pyd")):
            raise RuntimeError(f"FFCx stress cache was not fresh: {cache}")

        with runtime.activate(
            cache_root=cache,
            diagnostics_dir=diagnostics,
        ):
            form = fem.form((1.0 + term) * ufl.dx, jit_options={"cache_dir": cache})
            value = float(fem.assemble_scalar(form))

        expected = 1.0 + 1.0 / (power + 1)
        if not math.isclose(value, expected, rel_tol=2e-10, abs_tol=2e-10):
            raise RuntimeError(
                f"FFCx stress cycle {index} numerical mismatch: got {value}, expected {expected}"
            )

        modules = sorted(cache.rglob("*.pyd"))
        if not modules:
            raise RuntimeError(f"FFCx stress cycle {index} compiled no module")
        module_names = {path.name for path in modules}
        new_names = module_names - seen_module_names
        if not new_names:
            raise RuntimeError(
                f"FFCx stress cycle {index} did not produce a distinct generated module name"
            )
        seen_module_names.update(module_names)

        records = _compiler_records(diagnostics)
        cycle_records = records[before_records:]
        if not cycle_records:
            raise RuntimeError(f"FFCx stress cycle {index} recorded no TinyCC command")
        sources = sorted(cache.rglob("*.c"))
        if not sources:
            raise RuntimeError(f"FFCx stress cycle {index} retained no generated C source")
        _assert_idle(selector, baseline_environment, original_distribution)
        results.append(
            {
                "index": index,
                "power": power,
                "value": value,
                "expected": expected,
                "compiler_command_count": len(cycle_records),
                "module_names": sorted(module_names),
                "new_module_names": sorted(new_names),
                "generated_sources": [
                    {
                        "path": str(path.relative_to(cache)).replace("\\", "/"),
                        "sha256": _sha256(path),
                    }
                    for path in sources
                ],
            }
        )

    if len({name for result in results for name in result["new_module_names"]}) < _FFCX_CYCLES:
        raise RuntimeError("FFCx stress did not establish 20 distinct generated module identities")
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if os.environ.get("PYTHONHASHSEED") != "0":
        raise RuntimeError("TinyCC Phase-5 stress requires PYTHONHASHSEED=0")

    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    selector = _load_selector()
    runtime = _discover_tinycc(selector)
    baseline_environment = dict(os.environ)
    original_distribution = _dist.Distribution
    temporary_root = Path(tempfile.mkdtemp(prefix="tinycc-phase5-stress-")).resolve()

    cffi_results = _cffi_stress(
        selector,
        runtime,
        work=work,
        temporary_root=temporary_root,
        baseline_environment=baseline_environment,
        original_distribution=original_distribution,
    )
    ffcx_results = _ffcx_stress(
        selector,
        runtime,
        work=work,
        temporary_root=temporary_root,
        baseline_environment=baseline_environment,
        original_distribution=original_distribution,
    )
    _assert_idle(selector, baseline_environment, original_distribution)

    result = {
        "schema": 1,
        "kind": "tinycc-phase5-integrated-stress",
        "status": "pass",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "python_hash_seed": os.environ["PYTHONHASHSEED"],
        "selected_backend": runtime.selected_backend,
        "backend_cache_id": runtime.backend_cache_id,
        "backend_root": str(runtime.backend_root.resolve()),
        "stress": {
            "minimal_cffi_compile_load_cycles": {
                "required": _CFFI_CYCLES,
                "completed": len(cffi_results),
                "cycles": cffi_results,
            },
            "fresh_ffcx_modules": {
                "required": _FFCX_CYCLES,
                "completed": len(ffcx_results),
                "distinct_new_module_names": sorted(
                    {name for item in ffcx_results for name in item["new_module_names"]}
                ),
                "cycles": ffcx_results,
            },
        },
        "lifecycle": {
            "shared_runtime_idle_after_each_cycle": True,
            "environment_restored_after_each_cycle": True,
            "cffi_distribution_restored_after_each_cycle": True,
            "activation_precedes_ffcx_form_creation": True,
        },
        "note": (
            "Temporary compiled modules/caches remain only on the ephemeral CI runner; "
            "durable broad-corpus generated-C evidence is tracked separately by the Phase-5 manifest."
        ),
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "TinyCC Phase 5 integrated stress passed: "
        f"{len(cffi_results)} CFFI compile/load cycles, "
        f"{len(ffcx_results)} fresh FFCx modules"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
