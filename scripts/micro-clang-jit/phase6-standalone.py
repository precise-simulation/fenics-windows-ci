"""Phase 6 micro-Clang-only standalone/Nuitka qualification entry point."""

from __future__ import annotations

import argparse
import contextlib
import faulthandler
import importlib.util
import json
import math
import os
import subprocess
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


def _render_command(cmd: object) -> list[str]:
    if isinstance(cmd, (list, tuple)):
        return [str(part) for part in cmd]
    return [str(cmd)]


def _is_micro_clang_build_command(cmd: object) -> bool:
    parts = _render_command(cmd)
    if not parts:
        return False
    executable = Path(parts[0]).name.lower()
    if executable != "x86_64-w64-mingw32-clang.exe":
        return False
    lowered = {part.lower() for part in parts[1:]}
    return "--version" not in lowered and "-dumpmachine" not in lowered


@contextlib.contextmanager
def _capture_compiler_commands(records: list[dict[str, object]]):
    original_run = subprocess.run
    original_check_call = subprocess.check_call
    original_spawns: list[tuple[type, object]] = []
    seen: set[tuple[str, ...]] = {
        tuple(str(part) for part in record.get("command", []))
        for record in records
        if isinstance(record.get("command"), list)
    }

    def remember(cmd: object) -> None:
        if not _is_micro_clang_build_command(cmd):
            return
        parts = _render_command(cmd)
        key = tuple(parts)
        if key not in seen:
            seen.add(key)
            records.append({"command": parts})

    def capture(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        remember(cmd)
        return original_run(cmd, *args, **kwargs)

    def capture_check_call(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        remember(cmd)
        return original_check_call(cmd, *args, **kwargs)

    # In normal conda Python setuptools reaches subprocess.check_call directly,
    # but Nuitka can freeze/bind that launcher before this proof runs. Patch the
    # distutils compiler command boundary too; CFFI's MinGW backend must pass
    # every compile/link invocation through CCompiler.spawn.
    compiler_classes: list[type] = []
    try:
        from setuptools._distutils.ccompiler import CCompiler as SetuptoolsCCompiler
        compiler_classes.append(SetuptoolsCCompiler)
    except ImportError:
        pass
    try:
        from distutils.ccompiler import CCompiler as DistutilsCCompiler
        if DistutilsCCompiler not in compiler_classes:
            compiler_classes.append(DistutilsCCompiler)
    except ImportError:
        pass

    for compiler_class in compiler_classes:
        original_spawn = compiler_class.spawn

        def capture_spawn(self, cmd, *args, _original=original_spawn, **kwargs):  # noqa: ANN001, ANN002, ANN003
            remember(cmd)
            return _original(self, cmd, *args, **kwargs)

        original_spawns.append((compiler_class, original_spawn))
        compiler_class.spawn = capture_spawn

    subprocess.run = capture
    subprocess.check_call = capture_check_call
    try:
        yield
    finally:
        subprocess.run = original_run
        subprocess.check_call = original_check_call
        for compiler_class, original_spawn in reversed(original_spawns):
            compiler_class.spawn = original_spawn


def _minimal_cffi(
    runtime,
    work: Path,
    commands: list[dict[str, object]],
) -> Path:
    ffi = FFI()
    ffi.cdef("int phase6_value(void);")
    ffi.set_source("_phase6_cffi_probe", "int phase6_value(void){return 61;}")
    cache = runtime.cache_root(work / "cffi cache with spaces")
    with _capture_compiler_commands(commands):
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
    backend_root: Path,
) -> dict[str, object]:
    if not records:
        raise RuntimeError("standalone qualification captured no micro-Clang compiler commands")

    bundle_text = str(bundle.resolve()).lower()
    backend_text = str(backend_root.resolve()).lower()
    original_text = str(original_prefix).lower()
    rendered: list[str] = []
    development_paths: list[str] = []
    compiler_paths: list[str] = []

    for record in records:
        command = record.get("command")
        if not isinstance(command, list) or not command:
            raise RuntimeError(f"invalid compiler command record: {record!r}")
        text = " ".join(str(part) for part in command)
        rendered.append(text)
        lowered = text.lower()
        if original_text in lowered:
            raise RuntimeError(f"compiler command reached renamed original prefix: {text}")
        if any(token in lowered for token in (
            "microsoft visual studio",
            "windows kits",
            "\\backends\\llvm-mingw\\",
            "/backends/llvm-mingw/",
            "\\backends\\tinycc\\",
            "/backends/tinycc/",
            "tcc.exe",
            "gcc.exe",
            "g++.exe",
            "cl.exe",
            "link.exe",
        )):
            raise RuntimeError(f"compiler command reached forbidden compiler/development input: {text}")

        compiler = Path(str(command[0])).resolve()
        compiler_paths.append(str(compiler))
        if not str(compiler).lower().startswith(backend_text + os.sep.lower()):
            raise RuntimeError(f"compiler executable escaped micro-Clang backend: {compiler}")

        for index, part in enumerate(command):
            token = str(part)
            value = None
            if token in ("-I", "-L", "-B") and index + 1 < len(command):
                value = str(command[index + 1])
            elif token.startswith("-I") and len(token) > 2:
                value = token[2:]
            elif token.startswith("-L") and len(token) > 2:
                value = token[2:]
            elif token.startswith("-B") and len(token) > 2:
                value = token[2:]
            if value:
                try:
                    candidate = str(Path(value).resolve())
                except OSError:
                    candidate = value
                development_paths.append(candidate)
                if not candidate.lower().startswith(bundle_text + os.sep.lower()):
                    raise RuntimeError(
                        f"compiler development path escaped standalone bundle: {candidate}"
                    )

    if not development_paths:
        raise RuntimeError("standalone micro-Clang commands exposed no development include/library paths")
    return {
        "command_count": len(records),
        "compiler_paths": sorted(set(compiler_paths)),
        "development_paths": sorted(set(development_paths)),
        "commands": rendered,
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

        records: list[dict[str, object]] = []
        with _capture_compiler_commands(records):
            with runtime.activate(cache_root=cache, diagnostics_dir=diagnostics):
                ffcx_jit(
                    comm,
                    mpi_form,
                    jit_options={"cache_dir": cache, "cffi_verbose": True},
                )

        compile_counts = comm.allgather(len(records))
        if compile_counts[0] == 0:
            raise RuntimeError("standalone MPI rank 0 did not compile the fresh JIT form")
        if compile_counts[1] != 0:
            raise RuntimeError(
                f"standalone MPI non-root rank started an independent compile: {compile_counts}"
            )

        hermetic = None
        if comm.rank == 0:
            hermetic = _assert_hermetic_commands(
                records,
                bundle=bundle,
                original_prefix=original_prefix,
                backend_root=runtime.backend_root,
            )
        elif records:
            raise RuntimeError(f"standalone MPI rank 1 captured compiler commands: {records!r}")

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
                "compile_commands_by_rank": compile_counts,
                "cache_modules_by_rank": visible,
                "generated_pyd_count": len(modules),
                "generated_pyd": [str(path.resolve()) for path in modules],
                "compiler_hermeticity": hermetic,
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

    records: list[dict[str, object]] = []

    _progress(work, "cffi:minimal")
    cffi_module = _minimal_cffi(runtime, work, records)
    _progress(work, "cffi:minimal:ok")

    forms_cache = runtime.cache_root(work / "ffcx cache with spaces")
    with _capture_compiler_commands(records):
        with runtime.activate(
            cache_root=forms_cache,
            diagnostics_dir=diagnostics / "forms",
        ):
            forms = _run_forms(work, forms_cache)
    _progress(work, "forms:ok")

    hermetic = _assert_hermetic_commands(
        records,
        bundle=bundle,
        original_prefix=original_prefix,
        backend_root=backend_root,
    )

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
        "compiler_hermeticity": hermetic,
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
