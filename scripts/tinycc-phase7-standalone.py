"""Phase 7 TinyCC-only standalone/Nuitka qualification entry point."""

from __future__ import annotations

import argparse
import faulthandler
import importlib.util
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

import pefile
from cffi import FFI

REQUIRED_DLL_CHARACTERISTICS = 0x40 | 0x20 | 0x100


def _progress(work: Path, stage: str) -> None:
    diagnostics = work / "diagnostics"
    diagnostics.mkdir(parents=True, exist_ok=True)
    record = {"stage": stage, "time": time.time()}
    with (diagnostics / "phase7-progress.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
    print(f"PHASE7: {stage}", flush=True)


def _load_python_module(name: str, path: Path):
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


def _bundle_root() -> Path:
    configured = os.environ.get("FENICS_PHASE7_BUNDLE_ROOT")
    if configured:
        return Path(configured).resolve()
    return Path(sys.executable).resolve().parent


def _inspect_pe(path: Path) -> dict[str, object]:
    pe = pefile.PE(str(path), fast_load=False)
    imports = sorted(
        entry.dll.decode("ascii", errors="replace").lower()
        for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])
    )
    chars = int(pe.OPTIONAL_HEADER.DllCharacteristics)
    if "python3.dll" not in imports:
        raise RuntimeError(f"stable-ABI python3.dll import missing: {imports}")
    if any(name.startswith(("python312", "python313", "python314", "python315")) for name in imports):
        raise RuntimeError(f"minor-version Python import present: {imports}")
    if (chars & REQUIRED_DLL_CHARACTERISTICS) != REQUIRED_DLL_CHARACTERISTICS:
        raise RuntimeError(f"required PE mitigation bits missing: 0x{chars:x}")
    reloc = any(
        section.Name.rstrip(b"\0") == b".reloc" and section.SizeOfRawData
        for section in pe.sections
    )
    pdata = any(
        section.Name.rstrip(b"\0") == b".pdata" and section.SizeOfRawData
        for section in pe.sections
    )
    if not reloc or not pdata:
        raise RuntimeError(f"PE relocation/unwind metadata missing: reloc={reloc}, pdata={pdata}")
    return {
        "imports": imports,
        "dll_characteristics": chars,
        "reloc": bool(reloc),
        "pdata": bool(pdata),
    }


def _load_selector(jit_root: Path):
    path = jit_root / "runtime" / "fenics_jit_selector.py"
    if not path.is_file():
        raise RuntimeError(f"standalone shared JIT selector missing: {path}")
    return _load_python_module("_phase7_fenics_jit_selector", path)


def _minimal_cffi(runtime, work: Path) -> tuple[Path, str]:
    ffi = FFI()
    ffi.cdef("int phase7_value(void);")
    ffi.set_source("_phase7_cffi_probe", "int phase7_value(void){return 47;}")
    with runtime.activate(
        cache_root=runtime.cache_root(work / "cffi-cache"),
        diagnostics_dir=work / "diagnostics" / "cffi",
    ):
        output = Path(
            ffi.compile(tmpdir=str(work / "cffi build with spaces"), verbose=True)
        ).resolve()
    spec = importlib.util.spec_from_file_location("_phase7_cffi_probe", output)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load standalone CFFI probe: {output}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.lib.phase7_value() != 47:
        raise RuntimeError("standalone minimal CFFI result mismatch")

    poison = work / "foreign.obj"
    poison.write_bytes(b"not-an-object")
    rejected = ""
    bad = FFI()
    bad.cdef("int bad(void);")
    bad.set_source(
        "_phase7_negative_probe",
        "int bad(void){return 1;}",
        extra_objects=[str(poison)],
    )
    try:
        with runtime.activate(
            cache_root=runtime.cache_root(work / "negative-cache"),
            diagnostics_dir=work / "diagnostics" / "negative",
        ):
            bad.compile(tmpdir=str(work / "negative"), verbose=False)
    except Exception as exc:  # noqa: BLE001
        rejected = str(exc)
        if "rejects extra object" not in rejected:
            raise
    else:
        raise RuntimeError("standalone TinyCC accepted a foreign object input")
    return output, rejected


def _run_forms(work: Path, cache: Path) -> dict[str, object]:
    _progress(work, "forms:import-numpy")
    import numpy as np
    _progress(work, "forms:import-numpy:ok")

    _progress(work, "forms:import-ufl")
    import ufl
    _progress(work, "forms:import-ufl:ok")

    _progress(work, "forms:import-dolfinx")
    from dolfinx import fem, mesh
    _progress(work, "forms:import-dolfinx:ok")

    _progress(work, "forms:import-linear-problem")
    from dolfinx.fem.petsc import LinearProblem
    _progress(work, "forms:import-linear-problem:ok")

    _progress(work, "forms:import-mpi4py")
    from mpi4py import MPI
    _progress(work, "forms:import-mpi4py:ok")

    _progress(work, "forms:import-petsc4py")
    from petsc4py import PETSc
    _progress(work, "forms:import-petsc4py:ok")

    _progress(work, "forms:create-mesh")
    domain = mesh.create_unit_square(MPI.COMM_SELF, 12, 12)
    _progress(work, "forms:create-mesh:ok")
    V = fem.functionspace(domain, ("Lagrange", 1))
    u, v = ufl.TrialFunction(V), ufl.TestFunction(V)
    fdim = domain.topology.dim - 1
    facets = mesh.locate_entities_boundary(
        domain, fdim, lambda x: np.full(x.shape[1], True, dtype=bool)
    )
    bc = fem.dirichletbc(0.0, fem.locate_dofs_topological(V, fdim, facets), V)

    a = ufl.inner(ufl.grad(u), ufl.grad(v)) * ufl.dx
    L = fem.Constant(domain, PETSc.ScalarType(1.0)) * v * ufl.dx

    _progress(work, "forms:construct-poisson")
    started = time.perf_counter()
    problem = LinearProblem(
        a,
        L,
        bcs=[bc],
        petsc_options={"ksp_type": "preonly", "pc_type": "lu"},
        petsc_options_prefix="phase7_standalone_",
        jit_options={"cache_dir": cache},
    )
    _progress(work, "forms:construct-poisson:ok")
    _progress(work, "forms:solve-poisson")
    solution = problem.solve()
    _progress(work, "forms:solve-poisson:ok")
    first_s = time.perf_counter() - started
    norm = float(np.linalg.norm(solution.x.array))
    if not math.isfinite(norm) or norm <= 0:
        raise RuntimeError(f"standalone Poisson solution norm invalid: {norm}")

    generated_after_first = sorted(cache.rglob("*.pyd"))
    if not generated_after_first:
        raise RuntimeError("standalone Poisson JIT produced no cache module")

    started = time.perf_counter()
    problem2 = LinearProblem(
        a,
        L,
        bcs=[bc],
        petsc_options={"ksp_type": "preonly", "pc_type": "lu"},
        petsc_options_prefix="phase7_standalone_reload_",
        jit_options={"cache_dir": cache},
    )
    solution2 = problem2.solve()
    second_s = time.perf_counter() - started
    norm2 = float(np.linalg.norm(solution2.x.array))
    if abs(norm2 - norm) > 1.0e-10 * max(1.0, abs(norm)):
        raise RuntimeError(f"standalone cache-reuse solution mismatch: {norm} vs {norm2}")

    V3 = fem.functionspace(domain, ("Lagrange", 3))
    u3, v3 = ufl.TrialFunction(V3), ufl.TestFunction(V3)
    higher = (
        ufl.inner(ufl.grad(u3), ufl.grad(v3)) * ufl.dx
        + PETSc.ScalarType(0.125) * u3 * v3 * ufl.dx
    )
    fem.form(higher, jit_options={"cache_dir": cache})

    Vdg = fem.functionspace(domain, ("DG", 1))
    udg, vdg = ufl.TrialFunction(Vdg), ufl.TestFunction(Vdg)
    facet_form = (
        ufl.inner(ufl.jump(udg), ufl.jump(vdg)) * ufl.dS
        + PETSc.ScalarType(0.5) * udg * vdg * ufl.ds
        + PETSc.ScalarType(0.25) * udg * vdg * ufl.dx
    )
    fem.form(facet_form, jit_options={"cache_dir": cache})

    modules = sorted(cache.rglob("*.pyd"))
    return {
        "cache_root": str(cache.resolve()),
        "solution_norm": norm,
        "first_use_s": first_s,
        "cache_reuse_s": second_s,
        "generated_pyd_count": len(modules),
        "generated_pyd": [str(path.resolve()) for path in modules],
    }


def _read_commands(diagnostics: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(diagnostics.rglob("compiler-commands.jsonl")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                value = json.loads(raw)
                if isinstance(value, dict):
                    value["_record_path"] = str(path.resolve())
                    records.append(value)
    return records


def _assert_hermetic_commands(
    records: list[dict[str, object]],
    *,
    bundle: Path,
    original_prefix: Path,
) -> dict[str, object]:
    if not records:
        raise RuntimeError("standalone qualification captured no TinyCC compiler commands")
    original_text = str(original_prefix).lower()
    bundle_text = str(bundle).lower()
    rendered: list[str] = []
    include_paths: list[str] = []
    for record in records:
        command = record.get("command")
        if not isinstance(command, list):
            raise RuntimeError(f"invalid compiler command record: {record!r}")
        text = " ".join(str(part) for part in command)
        rendered.append(text)
        lowered = text.lower()
        if original_text in lowered:
            raise RuntimeError(f"compiler command reached renamed original prefix: {text}")
        forbidden = ("microsoft visual studio", "windows kits", "cl.exe", "clang", "gcc")
        if any(token in lowered for token in forbidden):
            raise RuntimeError(f"compiler command reached forbidden host toolchain input: {text}")
        for index, part in enumerate(command[:-1]):
            if str(part) == "-I":
                include_paths.append(str(command[index + 1]))
    if not include_paths:
        raise RuntimeError("standalone TinyCC commands contained no include paths")
    outside = [path for path in include_paths if bundle_text not in path.lower()]
    if outside:
        raise RuntimeError(f"standalone compiler include path escaped bundle: {outside!r}")
    return {
        "command_count": len(records),
        "include_paths": sorted(set(include_paths)),
        "commands": rendered,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, default=Path("phase7 standalone work"))
    parser.add_argument("--output", type=Path, default=Path("phase7-standalone-summary.json"))
    args = parser.parse_args()

    bundle = _bundle_root()
    jit_root = bundle / "fenics-jit"
    original_raw = os.environ.get("FENICS_PHASE7_ORIGINAL_PREFIX")
    if not original_raw:
        raise RuntimeError("FENICS_PHASE7_ORIGINAL_PREFIX is required")
    original_prefix = Path(original_raw)
    if original_prefix.exists():
        raise RuntimeError(f"original build prefix is still accessible: {original_prefix}")

    if (jit_root / "backends" / "llvm-mingw").exists():
        raise RuntimeError("LLVM-MinGW backend is present in TinyCC-only standalone bundle")
    if not (jit_root / "backends" / "tinycc" / "tcc.exe").is_file():
        raise RuntimeError("TinyCC compiler is missing from standalone bundle")

    configured_root = Path(os.environ.get("FENICS_JIT_ROOT", "")).resolve()
    if configured_root != jit_root.resolve():
        raise RuntimeError(f"FENICS_JIT_ROOT mismatch: {configured_root} != {jit_root}")
    if os.environ.get("FENICS_JIT_COMPILER") != "tinycc":
        raise RuntimeError("standalone proof requires FENICS_JIT_COMPILER=tinycc")

    python_headers = bundle / "include"
    if not (python_headers / "Python.h").is_file():
        raise RuntimeError(f"staged CPython headers missing: {python_headers}")
    if not list(bundle.rglob("ufcx.h")):
        raise RuntimeError("staged UFCx header missing from standalone bundle")

    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    faulthandler.enable(all_threads=True)
    diagnostics = work / "diagnostics"
    diagnostics.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(diagnostics)
    os.environ["TMP"] = str(diagnostics)
    tempfile.tempdir = str(diagnostics)

    _progress(work, "selector:load")
    selector = _load_selector(jit_root)
    runtime = selector.discover_runtime()
    _progress(work, "selector:load:ok")
    if runtime.selected_backend != "tinycc":
        raise RuntimeError(f"unexpected standalone backend: {runtime.selected_backend}")
    if not runtime.backend_root.resolve().is_relative_to(bundle):
        raise RuntimeError(f"TinyCC backend escaped bundle: {runtime.backend_root}")

    _progress(work, "cffi:minimal")
    cffi_module, rejection = _minimal_cffi(runtime, work)
    _progress(work, "cffi:minimal:ok")
    forms_cache = runtime.cache_root(work / "ffcx cache with spaces")
    with runtime.activate(
        cache_root=forms_cache,
        diagnostics_dir=diagnostics / "forms",
    ):
        forms = _run_forms(work, forms_cache)
    _progress(work, "forms:ok")
    commands = _read_commands(diagnostics)
    hermetic = _assert_hermetic_commands(
        commands, bundle=bundle, original_prefix=original_prefix
    )

    pe_records = [_inspect_pe(cffi_module)]
    for item in forms["generated_pyd"]:
        pe_records.append(_inspect_pe(Path(str(item))))

    runtime_bytes = sum(
        path.stat().st_size
        for path in (jit_root / "runtime").rglob("*")
        if path.is_file()
    )
    tinycc_bytes = sum(
        path.stat().st_size
        for path in (jit_root / "backends" / "tinycc").rglob("*")
        if path.is_file()
    )
    headers_bytes = sum(
        path.stat().st_size
        for path in bundle.rglob("*")
        if path.is_file()
        and (
            path.is_relative_to(bundle / "include")
            or path.name == "ufcx.h"
        )
    )

    summary = {
        "schema": 1,
        "kind": "tinycc-phase7-standalone-qualification",
        "status": "pass",
        "python": sys.version,
        "bundle_root": str(bundle),
        "jit_root": str(jit_root),
        "original_prefix": str(original_prefix),
        "original_prefix_accessible": original_prefix.exists(),
        "selected_backend": runtime.selected_backend,
        "backend_cache_id": runtime.backend_cache_id,
        "llvm_mingw_present": (jit_root / "backends" / "llvm-mingw").exists(),
        "cffi": {
            "module": str(cffi_module),
            "negative_input_rejection": rejection,
        },
        "forms": forms,
        "compiler_hermeticity": hermetic,
        "pe": pe_records,
        "footprint": {
            "common_runtime_bytes": runtime_bytes,
            "tinycc_incremental_bytes": tinycc_bytes,
            "staged_development_headers_bytes": headers_bytes,
        },
    }
    args.output.resolve().write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
