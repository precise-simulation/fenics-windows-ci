"""Phase 6 micro-Clang-only standalone/Nuitka qualification entry point."""

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
import traceback
from pathlib import Path

import pefile
from cffi import FFI

REQUIRED_DLL_CHARACTERISTICS = 0x40 | 0x20 | 0x100


def _progress(work: Path, stage: str) -> None:
    diagnostics = work / "diagnostics"
    diagnostics.mkdir(parents=True, exist_ok=True)
    record = {"stage": stage, "time": time.time()}
    with (diagnostics / "phase6-progress.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
    print(f"PHASE6: {stage}", flush=True)


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
    configured = os.environ.get("FENICS_PHASE6_BUNDLE_ROOT")
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
        "path": str(path.resolve()),
        "imports": imports,
        "dll_characteristics": chars,
        "reloc": bool(reloc),
        "pdata": bool(pdata),
    }


def _load_selector(jit_root: Path):
    path = jit_root / "runtime" / "fenics_jit_selector.py"
    if not path.is_file():
        raise RuntimeError(f"standalone shared JIT selector missing: {path}")
    return _load_python_module("_micro_clang_phase6_selector", path)


def _assert_bundle_runtime_config(config, *, bundle: Path, backend_root: Path, original_prefix: Path) -> dict[str, object]:
    selector_record = config.diagnostic_record()
    backend_record = selector_record.get("backend")
    record = backend_record if isinstance(backend_record, dict) else selector_record
    expected = {
        "toolchain_root": backend_root.resolve(),
        "clang": (backend_root / "bin" / "x86_64-w64-mingw32-clang.exe").resolve(),
        "lld": (backend_root / "bin" / "ld.lld.exe").resolve(),
    }
    for key, path in expected.items():
        actual = Path(str(record[key])).resolve()
        if actual != path:
            raise RuntimeError(f"standalone {key} mismatch: {actual} != {path}")
    bundle_root = bundle.resolve()
    keys = (
        "toolchain_root", "clang", "lld", "toolchain_include", "target_library_dir",
        "python_prefix", "python_include", "python_dll", "python_import_library_dir",
        "python_import_library", "python_stable_import_library", "ffcx_include",
    )
    resolved = {}
    for key in keys:
        path = Path(str(record[key])).resolve()
        if not path.is_relative_to(bundle_root):
            raise RuntimeError(f"standalone {key} escaped bundle: {path}")
        if str(original_prefix).lower() in str(path).lower():
            raise RuntimeError(f"standalone {key} reached hidden original prefix: {path}")
        resolved[key] = str(path)
    if record.get("runtime_dll_dir"):
        path = Path(str(record["runtime_dll_dir"])).resolve()
        if not path.is_relative_to(bundle_root):
            raise RuntimeError(f"standalone runtime DLL directory escaped bundle: {path}")
        resolved["runtime_dll_dir"] = str(path)
    for entry in os.environ.get("PATH","").split(os.pathsep):
        low=entry.lower()
        if "microsoft visual studio" in low or "windows kits" in low:
            raise RuntimeError(f"host compiler/SDK path leaked into standalone JIT PATH: {entry}")
    if Path(os.environ.get("CC","")).resolve()!=expected["clang"]:
        raise RuntimeError(f"standalone CC is not packaged micro-Clang: {os.environ.get('CC')}")
    if Path(os.environ.get("CXX","")).resolve()!=expected["clang"]:
        raise RuntimeError(f"standalone CXX is not packaged micro-Clang: {os.environ.get('CXX')}")
    return {"diagnostic_record":record,"resolved_bundle_paths":resolved,"cc":os.environ.get("CC"),"cxx":os.environ.get("CXX"),"path":os.environ.get("PATH")}


def _assert_ffcx_transcripts(cache: Path, *, bundle: Path, backend_root: Path, original_prefix: Path, config_record: dict[str, object]) -> dict[str, object]:
    markers=sorted(cache.rglob("*.c.cached"))
    if not markers:
        raise RuntimeError("standalone FFCx cache contains no completed compile transcript")
    texts=[p.read_text(encoding="utf-8",errors="replace") for p in markers]
    combined="\n".join(texts)
    lowered=combined.lower()
    if str(original_prefix).lower() in lowered:
        raise RuntimeError("FFCx compile transcript references the hidden original prefix")
    forbidden=("microsoft visual studio","windows kits","\\backends\\llvm-mingw\\","/backends/llvm-mingw/","\\backends\\tinycc\\","/backends/tinycc/","tcc.exe","gcc.exe","g++.exe","cl.exe","link.exe")
    leaked=[token for token in forbidden if token in lowered]
    if leaked:
        raise RuntimeError(f"FFCx compile transcript reached forbidden inputs: {leaked}")
    required={
        "clang":Path(str(config_record["clang"])).resolve(),
        "python_include":Path(str(config_record["python_include"])).resolve(),
        "ffcx_include":Path(str(config_record["ffcx_include"])).resolve(),
        "toolchain_include":Path(str(config_record["toolchain_include"])).resolve(),
        "python_import_library_dir":Path(str(config_record["python_import_library_dir"])).resolve(),
        "target_library_dir":Path(str(config_record["target_library_dir"])).resolve(),
    }
    missing=[]
    for key,path in required.items():
        if not path.is_relative_to(bundle.resolve()):
            raise RuntimeError(f"transcript-required {key} path escaped bundle: {path}")
        candidates={str(path).lower(),path.as_posix().lower(),str(path).replace("\\","/").lower()}
        if not any(candidate in lowered for candidate in candidates):
            missing.append(f"{key}={path}")
    if missing:
        raise RuntimeError("FFCx compile transcript does not expose all required bundle-local inputs: "+", ".join(missing))
    clang_name="x86_64-w64-mingw32-clang.exe"
    command_lines=[line.strip() for text in texts for line in text.splitlines() if clang_name in line.lower()]
    if not command_lines:
        raise RuntimeError("FFCx compile transcript contains no micro-Clang command line")
    return {"marker_count":len(markers),"markers":[str(p.resolve()) for p in markers],"micro_clang_command_count":len(command_lines),"micro_clang_commands":command_lines,"required_paths":{k:str(v) for k,v in required.items()}}


def _minimal_cffi(runtime, work: Path) -> Path:
    ffi = FFI()
    ffi.cdef("int phase6_value(void);")
    ffi.set_source("_phase6_cffi_probe", "int phase6_value(void){return 61;}")
    cache = runtime.cache_root(work / "cffi cache with spaces")
    with runtime.activate(
        cache_root=cache,
        diagnostics_dir=work / "diagnostics" / "cffi",
    ):
        output = Path(
            ffi.compile(tmpdir=str(work / "cffi build with spaces"), verbose=True)
        ).resolve()
    spec = importlib.util.spec_from_file_location("_phase6_cffi_probe", output)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load standalone CFFI probe: {output}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.lib.phase6_value() != 61:
        raise RuntimeError("standalone minimal CFFI result mismatch")
    return output


def _run_forms(work: Path, cache: Path) -> dict[str, object]:
    _progress(work, "forms:import-numpy")
    import numpy as np
    _progress(work, "forms:import-numpy:ok")

    _progress(work, "forms:import-ufl")
    import ufl
    _progress(work, "forms:import-ufl:ok")

    _progress(work, "forms:import-dolfinx")
    from dolfinx import fem, mesh
    from dolfinx.fem.petsc import LinearProblem
    _progress(work, "forms:import-dolfinx:ok")

    from mpi4py import MPI
    from petsc4py import PETSc

    domain = mesh.create_unit_square(MPI.COMM_SELF, 12, 12)
    V = fem.functionspace(domain, ("Lagrange", 1))
    u, v = ufl.TrialFunction(V), ufl.TestFunction(V)
    fdim = domain.topology.dim - 1
    facets = mesh.locate_entities_boundary(
        domain, fdim, lambda x: np.full(x.shape[1], True, dtype=bool)
    )
    bc = fem.dirichletbc(0.0, fem.locate_dofs_topological(V, fdim, facets), V)
    a = ufl.inner(ufl.grad(u), ufl.grad(v)) * ufl.dx
    L = fem.Constant(domain, PETSc.ScalarType(1.0)) * v * ufl.dx

    _progress(work, "forms:poisson:fresh")
    started = time.perf_counter()
    problem = LinearProblem(
        a,
        L,
        bcs=[bc],
        petsc_options={"ksp_type": "preonly", "pc_type": "lu"},
        petsc_options_prefix="micro_phase6_standalone_",
        jit_options={"cache_dir": cache},
    )
    solution = problem.solve()
    first_s = time.perf_counter() - started
    norm = float(np.linalg.norm(solution.x.array))
    if not math.isfinite(norm) or norm <= 0:
        raise RuntimeError(f"standalone Poisson solution norm invalid: {norm}")

    generated_after_first = sorted(cache.rglob("*.pyd"))
    if not generated_after_first:
        raise RuntimeError("standalone Poisson JIT produced no cache module")

    _progress(work, "forms:poisson:cache-reuse")
    started = time.perf_counter()
    problem2 = LinearProblem(
        a,
        L,
        bcs=[bc],
        petsc_options={"ksp_type": "preonly", "pc_type": "lu"},
        petsc_options_prefix="micro_phase6_standalone_reload_",
        jit_options={"cache_dir": cache},
    )
    solution2 = problem2.solve()
    second_s = time.perf_counter() - started
    norm2 = float(np.linalg.norm(solution2.x.array))
    if abs(norm2 - norm) > 1.0e-10 * max(1.0, abs(norm)):
        raise RuntimeError(f"standalone cache-reuse solution mismatch: {norm} vs {norm2}")

    _progress(work, "forms:representative")
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
    _progress(work, "forms:representative:ok")

    modules = sorted(cache.rglob("*.pyd"))
    return {
        "cache_root": str(cache.resolve()),
        "solution_norm": norm,
        "first_use_s": first_s,
        "cache_reuse_s": second_s,
        "generated_pyd_count": len(modules),
        "generated_pyd": [str(path.resolve()) for path in modules],
    }


def _run_mpi_child(
    runtime,
    work: Path,
    output: Path,
    bundle: Path,
    original_prefix: Path,
) -> int:
    import ufl
    from dolfinx import fem, mesh
    from dolfinx.jit import ffcx_jit
    from mpi4py import MPI
    from petsc4py import PETSc

    comm = MPI.COMM_WORLD
    try:
        if comm.size != 2:
            raise RuntimeError(f"Phase 6 standalone MPI proof requires exactly 2 ranks, got {comm.size}")

        identity = {
            "selected_backend": runtime.selected_backend,
            "backend_cache_id": runtime.backend_cache_id,
            "backend_root": str(runtime.backend_root.resolve()),
        }
        identities = comm.allgather(identity)
        if any(item != identities[0] for item in identities[1:]):
            raise RuntimeError(f"standalone MPI ranks selected different JIT runtimes: {identities!r}")

        cache = runtime.cache_root(work / "mpi ffcx cache with spaces")
        if " " not in str(cache):
            raise RuntimeError(f"standalone MPI cache path must contain spaces: {cache}")
        diagnostics = work / "diagnostics" / "mpi" / f"rank-{comm.rank}"
        diagnostics.mkdir(parents=True, exist_ok=True)

        domain = mesh.create_unit_square(comm, 3, 3)
        V = fem.functionspace(domain, ("Lagrange", 2))
        u, v = ufl.TrialFunction(V), ufl.TestFunction(V)
        beta = fem.Constant(domain, PETSc.ScalarType(4.375))
        mpi_form = (
            ufl.inner(ufl.grad(u), ufl.grad(v)) * ufl.dx
            + beta * u * v * ufl.dx
            + beta * u * v * ufl.ds
        )

        config_evidence = None
        transcript_evidence = None
        nonroot_poison = None
        with runtime.activate(cache_root=cache, diagnostics_dir=diagnostics) as config:
            if comm.rank == 0:
                config_evidence = _assert_bundle_runtime_config(
                    config, bundle=bundle, backend_root=runtime.backend_root,
                    original_prefix=original_prefix,
                )
            else:
                nonroot_poison = str(work / "nonroot compiler must not run.exe")
                os.environ["CC"] = nonroot_poison
                os.environ["CXX"] = nonroot_poison
            poison_values = comm.allgather(nonroot_poison)
            if poison_values[0] is not None or not poison_values[1]:
                raise RuntimeError(f"unexpected MPI compiler-poison state: {poison_values}")
            ffcx_jit(comm, mpi_form, jit_options={"cache_dir": cache, "cffi_verbose": True})
            if comm.rank == 0:
                transcript_evidence = _assert_ffcx_transcripts(
                    cache, bundle=bundle, backend_root=runtime.backend_root,
                    original_prefix=original_prefix,
                    config_record=config_evidence["diagnostic_record"],
                )
        compile_ownership = {
            "fresh_cache": True,
            "rank0_compiler": str(runtime.backend_root / "bin" / "x86_64-w64-mingw32-clang.exe"),
            "rank1_compiler_poison": poison_values[1],
            "rank1_compile_attempt_would_fail": True,
            "jit_completed": True,
        }
        comm.Barrier()
        modules = sorted(cache.rglob("*.pyd"))
        visible = comm.allgather([path.name for path in modules])
        if not visible[0] or any(item != visible[0] for item in visible[1:]):
            raise RuntimeError(
                f"standalone MPI ranks do not see the same JIT cache artifacts: {visible!r}"
            )

        if comm.rank == 0:
            summary = {
                "schema": 1,
                "kind": "micro-clang-phase6-standalone-mpi-qualification",
                "status": "pass",
                "ranks": comm.size,
                "bundle_root": str(bundle),
                "original_prefix": str(original_prefix),
                "original_prefix_accessible": original_prefix.exists(),
                "selected_backend": runtime.selected_backend,
                "backend_cache_id": runtime.backend_cache_id,
                "cache_root": str(cache),
                "compile_ownership": compile_ownership,
                "cache_modules_by_rank": visible,
                "generated_pyd_count": len(modules),
                "generated_pyd": [str(path.resolve()) for path in modules],
                "runtime_hermeticity": config_evidence,
                "ffcx_compile_transcript": transcript_evidence,
                "pe": [_inspect_pe(path) for path in modules],
            }
            output = output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
        comm.Barrier()
        return 0
    except BaseException:
        traceback.print_exc()
        sys.stderr.flush()
        try:
            comm.Abort(1)
        finally:
            os._exit(1)


def _require_backend_release_material(backend_root: Path) -> dict[str, object]:
    required = (
        "metadata.json",
        "manifest.csv",
        "size.txt",
        "provenance/build-provenance.json",
        "licenses/LLVM-LICENSE.TXT",
        "licenses/llvm-mingw-LICENSE.txt",
        "licenses/mingw-w64-COPYING",
        "lib/python/libpython3.a",
    )
    missing = [name for name in required if not (backend_root / Path(name)).is_file()]
    if missing:
        raise RuntimeError(f"standalone micro-Clang release material is missing: {missing}")
    return {
        "required_files": list(required),
        "metadata": json.loads((backend_root / "metadata.json").read_text(encoding="utf-8")),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, default=Path("phase6 standalone work"))
    parser.add_argument("--output", type=Path, default=Path("phase6-standalone-summary.json"))
    parser.add_argument("--mpi-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    bundle = _bundle_root()
    jit_root = bundle / "fenics-jit"
    backend_root = jit_root / "backends" / "micro-clang"

    original_raw = os.environ.get("FENICS_PHASE6_ORIGINAL_PREFIX")
    if not original_raw:
        raise RuntimeError("FENICS_PHASE6_ORIGINAL_PREFIX is required")
    original_prefix = Path(original_raw)
    if original_prefix.exists():
        raise RuntimeError(f"original build prefix is still accessible: {original_prefix}")

    if (jit_root / "backends" / "llvm-mingw").exists():
        raise RuntimeError("LLVM-MinGW backend is present in micro-Clang-only standalone bundle")
    if (jit_root / "backends" / "tinycc").exists():
        raise RuntimeError("TinyCC backend is present in micro-Clang-only standalone bundle")
    if not (backend_root / "bin" / "x86_64-w64-mingw32-clang.exe").is_file():
        raise RuntimeError("micro-Clang compiler is missing from standalone bundle")
    if not (backend_root / "bin" / "ld.lld.exe").is_file():
        raise RuntimeError("micro-Clang linker is missing from standalone bundle")

    configured_root = Path(os.environ.get("FENICS_JIT_ROOT", "")).resolve()
    if configured_root != jit_root.resolve():
        raise RuntimeError(f"FENICS_JIT_ROOT mismatch: {configured_root} != {jit_root}")
    if os.environ.get("FENICS_JIT_COMPILER") != "micro-clang":
        raise RuntimeError("standalone proof requires FENICS_JIT_COMPILER=micro-clang")

    python_headers = bundle / "include"
    if not (python_headers / "Python.h").is_file():
        raise RuntimeError(f"staged CPython headers missing: {python_headers}")
    ufcx_headers = list(bundle.rglob("ufcx.h"))
    if not ufcx_headers:
        raise RuntimeError("staged UFCx header missing from standalone bundle")
    release_material = _require_backend_release_material(backend_root)

    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    faulthandler.enable(all_threads=True)
    diagnostics = work / "diagnostics"
    diagnostics.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(diagnostics)
    os.environ["TMP"] = str(diagnostics)
    tempfile.tempdir = str(diagnostics)

    selector = _load_selector(jit_root)
    runtime = selector.discover_runtime()
    if runtime.selected_backend != "micro-clang":
        raise RuntimeError(f"unexpected standalone backend: {runtime.selected_backend}")
    if not runtime.backend_root.resolve().is_relative_to(bundle):
        raise RuntimeError(f"micro-Clang backend escaped bundle: {runtime.backend_root}")

    if args.mpi_child:
        return _run_mpi_child(runtime, work, args.output, bundle, original_prefix)

    _progress(work, "cffi:minimal")
    cffi_module = _minimal_cffi(runtime, work)
    _progress(work, "cffi:minimal:ok")

    forms_cache = runtime.cache_root(work / "ffcx cache with spaces")
    with runtime.activate(
        cache_root=forms_cache,
        diagnostics_dir=diagnostics / "forms",
    ) as config:
        runtime_hermeticity = _assert_bundle_runtime_config(
            config, bundle=bundle, backend_root=backend_root,
            original_prefix=original_prefix,
        )
        forms = _run_forms(work, forms_cache)
        transcript_evidence = _assert_ffcx_transcripts(
            forms_cache, bundle=bundle, backend_root=backend_root,
            original_prefix=original_prefix,
            config_record=runtime_hermeticity["diagnostic_record"],
        )
    _progress(work, "forms:ok")

    pe_records = [_inspect_pe(cffi_module)]
    for item in forms["generated_pyd"]:
        pe_records.append(_inspect_pe(Path(str(item))))

    runtime_bytes = sum(
        path.stat().st_size
        for path in (jit_root / "runtime").rglob("*")
        if path.is_file()
    )
    backend_bytes = sum(
        path.stat().st_size
        for path in backend_root.rglob("*")
        if path.is_file()
    )
    headers_bytes = sum(
        path.stat().st_size
        for path in bundle.rglob("*")
        if path.is_file()
        and (path.is_relative_to(bundle / "include") or path.name == "ufcx.h")
    )
    bundle_bytes = sum(path.stat().st_size for path in bundle.rglob("*") if path.is_file())

    summary = {
        "schema": 1,
        "kind": "micro-clang-phase6-standalone-qualification",
        "status": "pass",
        "python": sys.version,
        "bundle_root": str(bundle),
        "jit_root": str(jit_root),
        "original_prefix": str(original_prefix),
        "original_prefix_accessible": original_prefix.exists(),
        "selected_backend": runtime.selected_backend,
        "backend_cache_id": runtime.backend_cache_id,
        "llvm_mingw_present": (jit_root / "backends" / "llvm-mingw").exists(),
        "tinycc_present": (jit_root / "backends" / "tinycc").exists(),
        "cffi": {"module": str(cffi_module)},
        "forms": forms,
        "runtime_hermeticity": runtime_hermeticity,
        "ffcx_compile_transcript": transcript_evidence,
        "pe": pe_records,
        "release_material": release_material,
        "staged_ufcx_headers": [str(path.resolve()) for path in ufcx_headers],
        "footprint": {
            "bundle_bytes": bundle_bytes,
            "common_runtime_bytes": runtime_bytes,
            "micro_clang_incremental_bytes": backend_bytes,
            "common_runtime_plus_micro_clang_bytes": runtime_bytes + backend_bytes,
            "staged_development_headers_bytes": headers_bytes,
        },
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
