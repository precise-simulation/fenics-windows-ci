"""Phase 6 TinyCC vs LLVM-MinGW size and performance comparison."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Callable, Iterator

import cffi
import numpy as np
import ufl
from mpi4py import MPI

_STAGE_AW = {
    "qualification_run": 34580520920,
    "staged_mib": 215.19,
    "installed_mib": 216.43,
    "compressed_mib": 51.34,
}
_STAGE_AW_INSTALLED_BYTES = int(_STAGE_AW["installed_mib"] * 1024 * 1024)
_FOOTPRINT_GATE_BYTES = int(_STAGE_AW_INSTALLED_BYTES * 0.25)
_BACKENDS = ("llvm-mingw", "tinycc")


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


def _selector() -> ModuleType:
    path = Path(sys.prefix) / "Library" / "fenics-jit" / "runtime" / "fenics_jit_selector.py"
    if not path.is_file():
        raise RuntimeError(f"installed shared selector is missing: {path}")
    return _load_module(path, "_phase6_fenics_jit_selector")


@contextlib.contextmanager
def _selected_backend(name: str) -> Iterator[None]:
    had = "FENICS_JIT_COMPILER" in os.environ
    old = os.environ.get("FENICS_JIT_COMPILER")
    os.environ["FENICS_JIT_COMPILER"] = name
    try:
        yield
    finally:
        if had:
            assert old is not None
            os.environ["FENICS_JIT_COMPILER"] = old
        else:
            os.environ.pop("FENICS_JIT_COMPILER", None)


def _discover(selector: ModuleType, name: str):
    with _selected_backend(name):
        runtime = selector.discover_runtime()
    if runtime.selected_backend != name:
        raise RuntimeError(f"selector returned {runtime.selected_backend!r}, expected {name!r}")
    return runtime


def _summary(samples: list[float]) -> dict[str, object]:
    if not samples:
        raise RuntimeError("cannot summarize empty timing sample set")
    values = np.asarray(samples, dtype=np.float64)
    return {
        "samples_s": [float(value) for value in values],
        "count": int(values.size),
        "min_s": float(np.min(values)),
        "p25_s": float(np.percentile(values, 25)),
        "median_s": float(np.median(values)),
        "p75_s": float(np.percentile(values, 75)),
        "p90_s": float(np.percentile(values, 90)),
        "p95_s": float(np.percentile(values, 95)),
        "max_s": float(np.max(values)),
    }


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        raise RuntimeError(f"invalid non-positive timing denominator: {denominator}")
    return float(numerator / denominator)


def _render_command(cmd: object) -> str:
    if isinstance(cmd, (list, tuple)):
        return subprocess.list2cmdline([str(part) for part in cmd])
    return str(cmd)


def _is_compiler_command(backend: str, cmd: object) -> bool:
    text = _render_command(cmd).lower()
    if backend == "tinycc":
        return "tcc.exe" in text
    return "x86_64-w64-mingw32-clang.exe" in text


@dataclass
class _JITProbe:
    backend: str
    codegen_s: float = 0.0
    cffi_compile_s: float = 0.0
    compiler_s: float = 0.0
    compiler_commands: list[str] = field(default_factory=list)


@contextlib.contextmanager
def _instrument_jit(probe: _JITProbe) -> Iterator[None]:
    import ffcx.compiler

    original_codegen = ffcx.compiler.compile_ufl_objects
    original_cffi_compile = cffi.FFI.compile
    original_run = subprocess.run
    original_check_call = subprocess.check_call

    def timed_codegen(*args, **kwargs):  # noqa: ANN002, ANN003
        started = time.perf_counter()
        try:
            return original_codegen(*args, **kwargs)
        finally:
            probe.codegen_s += time.perf_counter() - started

    def timed_cffi_compile(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        started = time.perf_counter()
        try:
            return original_cffi_compile(self, *args, **kwargs)
        finally:
            probe.cffi_compile_s += time.perf_counter() - started

    def timed_run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        compiler = _is_compiler_command(probe.backend, cmd)
        started = time.perf_counter() if compiler else 0.0
        try:
            return original_run(cmd, *args, **kwargs)
        finally:
            if compiler:
                probe.compiler_s += time.perf_counter() - started
                probe.compiler_commands.append(_render_command(cmd))

    def timed_check_call(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        compiler = _is_compiler_command(probe.backend, cmd)
        started = time.perf_counter() if compiler else 0.0
        try:
            return original_check_call(cmd, *args, **kwargs)
        finally:
            if compiler:
                probe.compiler_s += time.perf_counter() - started
                probe.compiler_commands.append(_render_command(cmd))

    ffcx.compiler.compile_ufl_objects = timed_codegen
    cffi.FFI.compile = timed_cffi_compile
    subprocess.run = timed_run
    subprocess.check_call = timed_check_call
    try:
        yield
    finally:
        ffcx.compiler.compile_ufl_objects = original_codegen
        cffi.FFI.compile = original_cffi_compile
        subprocess.run = original_run
        subprocess.check_call = original_check_call


def _normalized_source_hashes(cache: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(cache.rglob("*.c")):
        text = path.read_text(encoding="utf-8")
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        records.append(
            {
                "path": path.relative_to(cache).as_posix(),
                "bytes": path.stat().st_size,
                "normalized_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            }
        )
    return records


def _jit_record(total_s: float, probe: _JITProbe, cache: Path) -> dict[str, object]:
    wrapper_build = max(0.0, probe.cffi_compile_s - probe.compiler_s)
    load_other = max(0.0, total_s - probe.codegen_s - probe.cffi_compile_s)
    return {
        "total_s": total_s,
        "ffcx_codegen_s": probe.codegen_s,
        "cffi_compile_total_s": probe.cffi_compile_s,
        "compiler_link_s": probe.compiler_s,
        "cffi_wrapper_build_overhead_s": wrapper_build,
        "module_load_and_other_s": load_other,
        "compiler_commands": probe.compiler_commands,
        "generated_sources": _normalized_source_hashes(cache),
    }


def _build_forms():
    from petsc4py import PETSc
    from dolfinx import fem, mesh

    domain = mesh.create_unit_square(MPI.COMM_SELF, 48, 48)
    tdim = domain.topology.dim
    fdim = tdim - 1
    domain.topology.create_connectivity(fdim, tdim)

    V1 = fem.functionspace(domain, ("Lagrange", 1))
    u1, v1 = ufl.TrialFunction(V1), ufl.TestFunction(V1)
    poisson = ufl.inner(ufl.grad(u1), ufl.grad(v1)) * ufl.dx

    Vv = fem.functionspace(domain, ("Lagrange", 1, (2,)))
    uv, vv = ufl.TrialFunction(Vv), ufl.TestFunction(Vv)
    mu = fem.Constant(domain, PETSc.ScalarType(2.0))
    lam = fem.Constant(domain, PETSc.ScalarType(3.0))
    eps_u = ufl.sym(ufl.grad(uv))
    eps_v = ufl.sym(ufl.grad(vv))
    sigma_u = 2.0 * mu * eps_u + lam * ufl.tr(eps_u) * ufl.Identity(2)
    elasticity = ufl.inner(sigma_u, eps_v) * ufl.dx

    V3 = fem.functionspace(domain, ("Lagrange", 3))
    u3, v3 = ufl.TrialFunction(V3), ufl.TestFunction(V3)
    higher_order = (
        ufl.inner(ufl.grad(u3), ufl.grad(v3)) * ufl.dx
        + PETSc.ScalarType(0.125) * u3 * v3 * ufl.dx
    )

    Vdg = fem.functionspace(domain, ("DG", 1))
    udg, vdg = ufl.TrialFunction(Vdg), ufl.TestFunction(Vdg)
    facet = (
        ufl.inner(ufl.jump(udg), ufl.jump(vdg)) * ufl.dS
        + PETSc.ScalarType(0.5) * udg * vdg * ufl.ds
        + PETSc.ScalarType(0.25) * udg * vdg * ufl.dx
    )

    coefficient = fem.Function(V1)
    coefficient.interpolate(lambda x: 1.0 + x[0] + 2.0 * x[1])
    alpha = fem.Constant(domain, PETSc.ScalarType(1.75))
    beta = fem.Constant(domain, PETSc.ScalarType(0.35))
    coefficient_heavy = (
        (coefficient * coefficient + alpha) * ufl.inner(ufl.grad(u1), ufl.grad(v1)) * ufl.dx
        + (coefficient + beta) * u1 * v1 * ufl.dx
        + alpha * u1 * v1 * ufl.ds
    )

    facets = mesh.exterior_facet_indices(domain.topology)
    dofs = fem.locate_dofs_topological(V1, fdim, facets)
    bc = fem.dirichletbc(PETSc.ScalarType(0), dofs, V1)
    source = fem.Constant(domain, PETSc.ScalarType(1.0))
    load = source * v1 * ufl.dx

    return {
        "domain": domain,
        "forms": {
            "scalar_poisson": poisson,
            "vector_elasticity": elasticity,
            "higher_order_p3": higher_order,
            "interior_exterior_facet_dg1": facet,
            "coefficient_heavy": coefficient_heavy,
        },
        "solve": {"a": poisson, "L": load, "bc": bc},
    }


def _jit_benchmark(
    selector: ModuleType,
    forms: dict[str, object],
    base_cache: Path,
    diagnostics: Path,
    repeats: int,
) -> dict[str, object]:
    from dolfinx.jit import ffcx_jit

    results: dict[str, object] = {}
    for backend in _BACKENDS:
        runtime = _discover(selector, backend)
        physical = runtime.cache_root(base_cache)
        backend_result: dict[str, object] = {
            "backend_cache_id": runtime.backend_cache_id,
            "physical_cache_root": str(physical),
            "forms": {},
        }
        for form_name, form in forms.items():
            cold_records: list[dict[str, object]] = []
            warm_records: list[dict[str, object]] = []
            for repeat in range(repeats):
                cache = physical / "phase6-jit" / form_name / f"repeat-{repeat}"
                shutil.rmtree(cache, ignore_errors=True)
                cache.mkdir(parents=True, exist_ok=True)
                diag = diagnostics / "jit" / backend / form_name / f"repeat-{repeat}"

                cold_probe = _JITProbe(backend)
                with runtime.activate(cache_root=physical, diagnostics_dir=diag / "cold"):
                    with _instrument_jit(cold_probe):
                        started = time.perf_counter()
                        ffcx_jit(MPI.COMM_SELF, form, jit_options={"cache_dir": cache})
                        cold_total = time.perf_counter() - started
                cold = _jit_record(cold_total, cold_probe, cache)
                if not cold_probe.compiler_commands or cold_probe.compiler_s <= 0:
                    raise RuntimeError(
                        f"cold {backend} JIT for {form_name} did not expose compiler timing"
                    )
                cold_records.append(cold)

                warm_probe = _JITProbe(backend)
                with runtime.activate(cache_root=physical, diagnostics_dir=diag / "warm"):
                    with _instrument_jit(warm_probe):
                        started = time.perf_counter()
                        ffcx_jit(MPI.COMM_SELF, form, jit_options={"cache_dir": cache})
                        warm_total = time.perf_counter() - started
                warm = _jit_record(warm_total, warm_probe, cache)
                if warm_probe.compiler_commands:
                    raise RuntimeError(
                        f"warm {backend} cache hit for {form_name} unexpectedly invoked compiler: "
                        f"{warm_probe.compiler_commands}"
                    )
                warm_records.append(warm)

            fields = (
                "total_s",
                "ffcx_codegen_s",
                "cffi_compile_total_s",
                "compiler_link_s",
                "cffi_wrapper_build_overhead_s",
                "module_load_and_other_s",
            )
            backend_result["forms"][form_name] = {
                "cold": {key: _summary([float(item[key]) for item in cold_records]) for key in fields},
                "warm": {key: _summary([float(item[key]) for item in warm_records]) for key in fields},
                "raw_cold": cold_records,
                "raw_warm": warm_records,
            }
        results[backend] = backend_result

    comparisons: dict[str, object] = {}
    for form_name in forms:
        llvm = results["llvm-mingw"]["forms"][form_name]
        tiny = results["tinycc"]["forms"][form_name]
        comparisons[form_name] = {
            "cold_total_ratio_tinycc_over_llvm": _ratio(
                tiny["cold"]["total_s"]["median_s"], llvm["cold"]["total_s"]["median_s"]
            ),
            "compiler_link_ratio_tinycc_over_llvm": _ratio(
                tiny["cold"]["compiler_link_s"]["median_s"],
                llvm["cold"]["compiler_link_s"]["median_s"],
            ),
            "warm_cache_ratio_tinycc_over_llvm": _ratio(
                tiny["warm"]["total_s"]["median_s"], llvm["warm"]["total_s"]["median_s"]
            ),
        }
    return {"backends": results, "comparisons": comparisons}


def _compile_runtime_forms(
    selector: ModuleType,
    forms: dict[str, object],
    solve: dict[str, object],
    base_cache: Path,
    diagnostics: Path,
) -> dict[str, object]:
    from dolfinx import fem

    compiled: dict[str, object] = {}
    for backend in _BACKENDS:
        runtime = _discover(selector, backend)
        physical = runtime.cache_root(base_cache)
        cache = physical / "phase6-runtime"
        shutil.rmtree(cache, ignore_errors=True)
        cache.mkdir(parents=True, exist_ok=True)
        with runtime.activate(
            cache_root=physical,
            diagnostics_dir=diagnostics / "runtime-compile" / backend,
        ):
            compiled_forms = {
                name: fem.form(form, jit_options={"cache_dir": cache}) for name, form in forms.items()
            }
            compiled_a = fem.form(solve["a"], jit_options={"cache_dir": cache})
            compiled_L = fem.form(solve["L"], jit_options={"cache_dir": cache})
        compiled[backend] = {
            "forms": compiled_forms,
            "solve_a": compiled_a,
            "solve_L": compiled_L,
            "backend_cache_id": runtime.backend_cache_id,
            "cache": str(cache),
        }
    return compiled


def _assemble_matrix_once(form) -> tuple[float, float]:  # noqa: ANN001
    from dolfinx.fem.petsc import assemble_matrix

    started = time.perf_counter()
    matrix = assemble_matrix(form)
    matrix.assemble()
    elapsed = time.perf_counter() - started
    norm = float(matrix.norm())
    matrix.destroy()
    return elapsed, norm


def _runtime_benchmark(compiled: dict[str, object], repeats: int) -> dict[str, object]:
    results: dict[str, object] = {}
    for form_name in compiled["llvm-mingw"]["forms"]:
        samples = {backend: [] for backend in _BACKENDS}
        norms = {backend: [] for backend in _BACKENDS}
        for _ in range(2):
            for backend in _BACKENDS:
                _assemble_matrix_once(compiled[backend]["forms"][form_name])
        for index in range(repeats):
            order = _BACKENDS if index % 2 == 0 else tuple(reversed(_BACKENDS))
            for backend in order:
                elapsed, norm = _assemble_matrix_once(compiled[backend]["forms"][form_name])
                samples[backend].append(elapsed)
                norms[backend].append(norm)
        llvm_norm = statistics.median(norms["llvm-mingw"])
        tiny_norm = statistics.median(norms["tinycc"])
        if not math.isclose(llvm_norm, tiny_norm, rel_tol=1e-10, abs_tol=1e-11):
            raise RuntimeError(
                f"assembly numerical mismatch for {form_name}: llvm={llvm_norm}, tinycc={tiny_norm}"
            )
        llvm_summary = _summary(samples["llvm-mingw"])
        tiny_summary = _summary(samples["tinycc"])
        results[form_name] = {
            "llvm-mingw": llvm_summary,
            "tinycc": tiny_summary,
            "median_ratio_tinycc_over_llvm": _ratio(
                tiny_summary["median_s"], llvm_summary["median_s"]
            ),
            "matrix_norm": {"llvm-mingw": llvm_norm, "tinycc": tiny_norm},
        }
    return results


def _solve_once(a, L, bc) -> dict[str, float]:  # noqa: ANN001
    from petsc4py import PETSc
    from dolfinx.fem.petsc import apply_lifting, assemble_matrix, assemble_vector, set_bc

    assembly_started = time.perf_counter()
    matrix = assemble_matrix(a, bcs=[bc])
    matrix.assemble()
    vector = assemble_vector(L)
    apply_lifting(vector, [a], bcs=[[bc]])
    vector.ghostUpdate(addv=PETSc.InsertMode.ADD_VALUES, mode=PETSc.ScatterMode.REVERSE)
    set_bc(vector, [bc])
    assembly_s = time.perf_counter() - assembly_started

    solution = matrix.createVecRight()
    solver_started = time.perf_counter()
    ksp = PETSc.KSP().create(MPI.COMM_SELF)
    ksp.setOperators(matrix)
    ksp.setType("cg")
    ksp.getPC().setType("jacobi")
    ksp.setTolerances(rtol=1e-10, max_it=2000)
    ksp.setUp()
    ksp.solve(vector, solution)
    solver_s = time.perf_counter() - solver_started
    if ksp.getConvergedReason() <= 0:
        raise RuntimeError(f"Phase-6 Poisson KSP did not converge: reason={ksp.getConvergedReason()}")
    norm = float(solution.norm())
    if not math.isfinite(norm) or norm <= 0:
        raise RuntimeError(f"Phase-6 Poisson solve produced invalid norm: {norm}")

    ksp.destroy()
    solution.destroy()
    vector.destroy()
    matrix.destroy()
    return {
        "assembly_s": assembly_s,
        "solver_s": solver_s,
        "total_s": assembly_s + solver_s,
        "solution_norm": norm,
    }


def _solve_benchmark(compiled: dict[str, object], bc, repeats: int) -> dict[str, object]:  # noqa: ANN001
    raw = {backend: [] for backend in _BACKENDS}
    for _ in range(1):
        for backend in _BACKENDS:
            _solve_once(compiled[backend]["solve_a"], compiled[backend]["solve_L"], bc)
    for index in range(max(3, repeats // 2)):
        order = _BACKENDS if index % 2 == 0 else tuple(reversed(_BACKENDS))
        for backend in order:
            raw[backend].append(
                _solve_once(compiled[backend]["solve_a"], compiled[backend]["solve_L"], bc)
            )

    llvm_norm = statistics.median(item["solution_norm"] for item in raw["llvm-mingw"])
    tiny_norm = statistics.median(item["solution_norm"] for item in raw["tinycc"])
    if not math.isclose(llvm_norm, tiny_norm, rel_tol=1e-10, abs_tol=1e-11):
        raise RuntimeError(f"Poisson solution mismatch: llvm={llvm_norm}, tinycc={tiny_norm}")

    result: dict[str, object] = {"raw": raw, "solution_norm": {"llvm-mingw": llvm_norm, "tinycc": tiny_norm}}
    for backend in _BACKENDS:
        result[backend] = {
            key: _summary([float(item[key]) for item in raw[backend]])
            for key in ("assembly_s", "solver_s", "total_s")
        }
    result["ratios_tinycc_over_llvm"] = {
        key: _ratio(result["tinycc"][key]["median_s"], result["llvm-mingw"][key]["median_s"])
        for key in ("assembly_s", "solver_s", "total_s")
    }
    return result


def _package_record(prefix: Path, name: str) -> dict[str, object]:
    matches = sorted((prefix / "conda-meta").glob(f"{name}-*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one installed {name} record, got {matches}")
    data = json.loads(matches[0].read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"invalid conda record for {name}: {matches[0]}")
    return data


def _owned_files(prefix: Path, record: dict[str, object]) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    for raw in record.get("files", []):
        relative = str(raw).replace("\\", "/")
        path = prefix / Path(relative)
        if not path.is_file():
            raise RuntimeError(f"installed package-owned file is missing: {path}")
        result.append((relative, path.stat().st_size))
    if not result:
        raise RuntimeError(f"installed package record has no files: {record.get('name')}")
    return result


def _tinycc_category(relative: str) -> str:
    lowered = relative.lower()
    name = Path(relative).name.lower()
    if "/include/" in lowered:
        return "headers"
    if "/lib/" in lowered or name == "python3.def":
        return "runtime_and_import_definitions"
    if name in {"tcc.exe", "libtcc.dll"}:
        return "compiler_binaries"
    if name.endswith(".py") or name.endswith(".json"):
        return "adapter_helpers_metadata"
    if "/licenses/" in lowered:
        return "licenses"
    return "other"


def _archive_records(package_dir: Path, package: str) -> list[dict[str, object]]:
    records = []
    for path in sorted(package_dir.rglob(f"{package}-*.conda")):
        records.append({"path": str(path.resolve()), "bytes": path.stat().st_size})
    if not records:
        raise RuntimeError(f"no {package} .conda archive found below {package_dir}")
    return records


def _footprint(package_dir: Path) -> dict[str, object]:
    prefix = Path(sys.prefix).resolve()
    tiny_record = _package_record(prefix, "fenics-jit-tinycc")
    runtime_record = _package_record(prefix, "fenics-jit-runtime")
    llvm_record = _package_record(prefix, "fenics-jit-llvm-mingw")

    tiny_files = _owned_files(prefix, tiny_record)
    runtime_files = _owned_files(prefix, runtime_record)
    llvm_files = _owned_files(prefix, llvm_record)
    tiny_bytes = sum(size for _, size in tiny_files)
    runtime_bytes = sum(size for _, size in runtime_files)
    llvm_bytes = sum(size for _, size in llvm_files)

    categories: dict[str, dict[str, int]] = {}
    for relative, size in tiny_files:
        category = _tinycc_category(relative)
        entry = categories.setdefault(category, {"bytes": 0, "files": 0})
        entry["bytes"] += size
        entry["files"] += 1

    tiny_archives = _archive_records(package_dir, "fenics-jit-tinycc")
    runtime_archives = _archive_records(package_dir, "fenics-jit-runtime")
    llvm_archives = _archive_records(package_dir, "fenics-jit-llvm-mingw")
    compressed_tiny = min(int(item["bytes"]) for item in tiny_archives)

    if tiny_bytes > _FOOTPRINT_GATE_BYTES:
        raise RuntimeError(
            f"TinyCC installed payload {tiny_bytes} exceeds Phase-6 footprint gate {_FOOTPRINT_GATE_BYTES}"
        )

    return {
        "stage_aw_reference": {
            **_STAGE_AW,
            "installed_bytes_from_rounded_mib": _STAGE_AW_INSTALLED_BYTES,
            "footprint_gate_bytes": _FOOTPRINT_GATE_BYTES,
        },
        "tinycc_backend": {
            "package": tiny_record.get("name"),
            "version": tiny_record.get("version"),
            "build": tiny_record.get("build"),
            "file_count": len(tiny_files),
            "staged_payload_bytes": tiny_bytes,
            "installed_payload_bytes": tiny_bytes,
            "staged_payload_method": "package-owned backend payload copied byte-for-byte into the install prefix",
            "installed_mib": tiny_bytes / (1024 * 1024),
            "percent_of_stage_aw_installed": 100.0 * tiny_bytes / _STAGE_AW_INSTALLED_BYTES,
            "compressed_archives": tiny_archives,
            "compressed_min_bytes": compressed_tiny,
            "categories": categories,
        },
        "common_runtime": {
            "file_count": len(runtime_files),
            "installed_bytes": runtime_bytes,
            "installed_mib": runtime_bytes / (1024 * 1024),
            "compressed_archives": runtime_archives,
        },
        "standalone_incremental": {
            "definition": "fenics-jit-runtime plus fenics-jit-tinycc package-owned installed files",
            "installed_bytes": runtime_bytes + tiny_bytes,
            "installed_mib": (runtime_bytes + tiny_bytes) / (1024 * 1024),
        },
        "current_branch_llvm_backend": {
            "file_count": len(llvm_files),
            "installed_bytes": llvm_bytes,
            "installed_mib": llvm_bytes / (1024 * 1024),
            "compressed_archives": llvm_archives,
        },
        "footprint_gate_pass": True,
    }


def _classify(
    footprint: dict[str, object],
    assembly: dict[str, object],
    jit: dict[str, object],
) -> dict[str, object]:
    ratios = [float(record["median_ratio_tinycc_over_llvm"]) for record in assembly.values()]
    jit_ratios = [
        float(record["cold_total_ratio_tinycc_over_llvm"])
        for record in jit["comparisons"].values()
    ]
    within_25 = sum(ratio <= 1.25 for ratio in ratios)
    worst = max(ratios)
    median_ratio = float(statistics.median(ratios))
    size_ok = bool(footprint["footprint_gate_pass"])

    if size_ok and within_25 >= max(1, math.ceil(len(ratios) * 0.8)) and worst <= 1.5:
        classification = "default-candidate"
        reason = "at least 80% of assembly families are within 25% and no median regression exceeds 1.5x"
    elif size_ok and median_ratio <= 3.0 and sum(ratio <= 3.0 for ratio in ratios) >= max(1, math.ceil(len(ratios) * 0.8)):
        classification = "compact-fallback-candidate"
        reason = "footprint gate passes and at least 80% of assembly families are within the 3x compact-backend envelope"
    else:
        classification = "reject"
        reason = "measured size/runtime results do not satisfy the Phase-6 candidate envelopes"

    return {
        "classification": classification,
        "reason": reason,
        "assembly_family_count": len(ratios),
        "assembly_ratios_tinycc_over_llvm": ratios,
        "assembly_median_ratio": median_ratio,
        "assembly_worst_ratio": worst,
        "families_within_25_percent": within_25,
        "families_within_3x": sum(ratio <= 3.0 for ratio in ratios),
        "jit_cold_ratios_tinycc_over_llvm": jit_ratios,
        "jit_cold_median_ratio": float(statistics.median(jit_ratios)),
        "jit_cold_worst_ratio": max(jit_ratios),
        "footprint_percent_of_stage_aw": footprint["tinycc_backend"]["percent_of_stage_aw_installed"],
        "note": "per-Python classification; the final Phase-6 decision must aggregate Python 3.12-3.14 evidence",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--diagnostics-dir", required=True, type=Path)
    parser.add_argument("--package-dir", required=True, type=Path)
    parser.add_argument("--jit-repeats", type=int, default=3)
    parser.add_argument("--runtime-repeats", type=int, default=9)
    args = parser.parse_args()
    if args.jit_repeats < 3:
        raise RuntimeError("Phase 6 requires at least 3 cold/warm JIT repetitions")
    if args.runtime_repeats < 5:
        raise RuntimeError("Phase 6 requires at least 5 runtime repetitions")
    if MPI.COMM_WORLD.size != 1:
        raise RuntimeError("Phase-6 benchmark must run in a single-rank process")

    diagnostics = args.diagnostics_dir.resolve()
    base_cache = args.cache_dir.resolve()
    package_dir = args.package_dir.resolve()
    diagnostics.mkdir(parents=True, exist_ok=True)
    base_cache.mkdir(parents=True, exist_ok=True)

    selector = _selector()
    model = _build_forms()
    footprint = _footprint(package_dir)
    jit = _jit_benchmark(
        selector,
        model["forms"],
        base_cache,
        diagnostics,
        args.jit_repeats,
    )
    compiled = _compile_runtime_forms(
        selector,
        model["forms"],
        model["solve"],
        base_cache,
        diagnostics,
    )
    assembly = _runtime_benchmark(compiled, args.runtime_repeats)
    solve = _solve_benchmark(compiled, model["solve"]["bc"], args.runtime_repeats)
    classification = _classify(footprint, assembly, jit)

    result = {
        "schema": 1,
        "kind": "tinycc-phase6-size-performance-comparison",
        "status": "pass",
        "python": {
            "version": sys.version,
            "major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
            "executable": sys.executable,
            "prefix": sys.prefix,
        },
        "measurement_policy": {
            "runner": os.environ.get("RUNNER_OS", "unknown"),
            "jit_repeats": args.jit_repeats,
            "runtime_repeats": args.runtime_repeats,
            "timing_clock": "time.perf_counter",
            "cold_cache": "unique cache subdirectory per backend/form/repetition inside the qualified backend-cache namespace",
            "warm_cache": "immediate second FFCx JIT lookup in the identical physical cache namespace",
            "runtime_order": "alternating LLVM-MinGW/TinyCC sample order to reduce runner drift",
            "percentiles": [25, 50, 75, 90, 95],
        },
        "footprint": footprint,
        "jit_latency": jit,
        "assembly_runtime": assembly,
        "end_to_end_poisson": solve,
        "provisional_classification": classification,
    }
    output = diagnostics / "phase6-summary.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "python": result["python"]["major_minor"],
        "tinycc_installed_mib": footprint["tinycc_backend"]["installed_mib"],
        "classification": classification["classification"],
        "assembly_median_ratio": classification["assembly_median_ratio"],
        "assembly_worst_ratio": classification["assembly_worst_ratio"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
