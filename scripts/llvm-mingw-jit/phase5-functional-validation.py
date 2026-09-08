"""Phase 5 functional validation for the packaged Windows FFCx JIT runtime."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

import numpy as np
import ufl
from mpi4py import MPI


def _poison_compiler_environment(root: Path) -> None:
    poison = root / "ambient poison" / "Microsoft Visual Studio"
    sdk = root / "ambient poison" / "Windows Kits"
    os.environ.update(
        {
            "VSINSTALLDIR": str(poison),
            "VCINSTALLDIR": str(poison / "VC"),
            "VCToolsInstallDir": str(poison / "VC" / "Tools"),
            "INCLUDE": str(sdk / "Include"),
            "LIB": str(sdk / "Lib"),
            "LIBPATH": str(sdk / "LibPath"),
            "LIBRARY_PATH": str(root / "ambient poison" / "library"),
            "WindowsSdkDir": str(sdk),
            "WindowsSDKVersion": "poison",
            "UniversalCRTSdkDir": str(sdk / "UCRT"),
            "UCRTVersion": "poison",
            "DISTUTILS_USE_SDK": "1",
            "MSSdk": "1",
            "CC": "cl.exe",
            "CXX": "cl.exe",
            "CPP": "cl.exe /E",
            "LD": "link.exe",
            "LDSHARED": "link.exe /DLL",
            "VSCMD_ARG_TGT_ARCH": "x64",
            "CPATH": str(root / "ambient poison" / "cp"),
            "C_INCLUDE_PATH": str(root / "ambient poison" / "c-include"),
            "CPLUS_INCLUDE_PATH": str(root / "ambient poison" / "cxx-include"),
            "COMPILER_PATH": str(root / "ambient poison" / "compiler"),
            "GCC_EXEC_PREFIX": str(root / "ambient poison" / "gcc"),
        }
    )


def _measurement_enabled() -> bool:
    return os.getenv("FENICS_JIT_MEASURE_CLOSURE", "").lower() in {"1", "true", "yes", "on"}


def _is_packaged_clang_command(cmd: object) -> bool:
    if not isinstance(cmd, (list, tuple)) or not cmd:
        return False
    return Path(str(cmd[0])).name.lower() in {
        "x86_64-w64-mingw32-clang.exe",
        "clang-23.exe",
    }


def _decode_subprocess_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


@contextlib.contextmanager
def _record_check_calls(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    calls: list[str] = []
    original = subprocess.check_call
    measurement = _measurement_enabled()
    trace_root = path.parent / "closure traces"
    if measurement:
        trace_root.mkdir(parents=True, exist_ok=True)
    call_index = 0

    def logged(cmd, *args, **kwargs):
        nonlocal call_index
        instrumented = list(cmd) if isinstance(cmd, (list, tuple)) else cmd
        trace_kind = None
        trace_path = None

        if measurement and _is_packaged_clang_command(cmd) and isinstance(instrumented, list):
            call_index += 1
            instrumented = [str(part) for part in instrumented]
            stem = f"{path.stem}-{call_index:03d}"
            if "-c" in instrumented:
                trace_kind = "header"
                depfile = trace_root / f"{stem}.d"
                trace_path = trace_root / f"{stem}-header-trace.txt"
                instrumented.extend(["-H", "-MD", "-MF", str(depfile)])
            elif "-shared" in instrumented:
                trace_kind = "linker"
                trace_path = trace_root / f"{stem}-linker-trace.txt"
                instrumented.append("-Wl,--trace")

        if isinstance(instrumented, list):
            rendered = subprocess.list2cmdline([str(part) for part in instrumented])
        else:
            rendered = str(instrumented)
        calls.append(rendered)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(rendered + "\n")

        if trace_kind is None or args:
            return original(instrumented, *args, **kwargs)

        run_kwargs = dict(kwargs)
        run_kwargs.setdefault("stdout", subprocess.PIPE)
        run_kwargs.setdefault("stderr", subprocess.PIPE)
        run_kwargs.setdefault("text", True)
        result = subprocess.run(instrumented, check=False, **run_kwargs)
        stdout = _decode_subprocess_output(result.stdout)
        stderr = _decode_subprocess_output(result.stderr)
        assert trace_path is not None
        trace_path.write_text(stdout + stderr, encoding="utf-8")

        if result.returncode:
            if stdout:
                sys.stdout.write(stdout)
            if stderr:
                sys.stderr.write(stderr)
            raise subprocess.CalledProcessError(
                result.returncode,
                instrumented,
                output=result.stdout,
                stderr=result.stderr,
            )
        return 0

    subprocess.check_call = logged
    try:
        yield calls
    finally:
        subprocess.check_call = original

def _load_runtime():
    runtime_path = Path(sys.prefix) / "Library" / "fenics-jit" / "runtime" / "fenics_jit_runtime.py"
    if not runtime_path.is_file():
        raise RuntimeError(f"Packaged JIT runtime helper missing: {runtime_path}")
    name = "_phase5_fenics_jit_runtime"
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, runtime_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load JIT runtime helper: {runtime_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


def _runtime_record() -> dict[str, object]:
    runtime = _load_runtime()
    config = runtime.RuntimeConfig.discover()
    record = config.diagnostic_record()
    expected_root = Path(sys.prefix).resolve() / "Library" / "fenics-jit"
    if Path(str(record["toolchain_root"])).resolve() != expected_root:
        raise RuntimeError(f"JIT helper selected wrong toolchain root: {record['toolchain_root']}")
    if record["backend"] != "mingw32" or record["crt"] != "UCRT":
        raise RuntimeError(f"Unexpected JIT runtime configuration: {record}")
    if not re.match(r"(?i)^x86_64-w64-(?:mingw32|windows-gnu)$", str(record["clang_reported_target"])):
        raise RuntimeError(f"Unexpected JIT target: {record['clang_reported_target']}")
    return record


def _assert_compiler_commands(calls: list[str], record: dict[str, object], *, require_compile: bool) -> None:
    text = "\n".join(calls)
    if require_compile and "x86_64-w64-mingw32-clang.exe" not in text:
        raise RuntimeError("Fresh JIT did not invoke packaged LLVM-MinGW Clang")
    if re.search(r'(?i)(?:^|[\\/\s"])cl\.exe(?:$|[\s"])', text):
        raise RuntimeError("Fresh JIT fell back to cl.exe")
    if re.search(r'(?i)(?:^|[\\/\s"])link\.exe(?:$|[\s"])', text):
        raise RuntimeError("Fresh JIT fell back to MSVC link.exe")
    for forbidden in ("Microsoft Visual Studio", "Windows Kits", "ambient poison"):
        if forbidden.lower() in text.lower():
            raise RuntimeError(f"Host compiler/SDK input leaked into JIT command: {forbidden}")
    if require_compile:
        for flag in ("-std=c17", "-D__STDC_NO_COMPLEX__"):
            if flag not in text:
                raise RuntimeError(f"Fresh JIT compiler commands missing required flag: {flag}")
        for key in ("python_include", "ffcx_include", "toolchain_include", "python_import_library_dir", "target_library_dir"):
            selected = str(record[key])
            if selected.lower() not in text.lower():
                raise RuntimeError(f"Fresh JIT commands do not contain helper-selected {key}: {selected}")


def _inspect_pyds(cache_dirs: list[Path], diagnostics: Path) -> list[Path]:
    readobj = Path(sys.prefix) / "Library" / "fenics-jit" / "bin" / "llvm-readobj.exe"
    if not readobj.is_file():
        raise RuntimeError(f"Packaged llvm-readobj missing: {readobj}")
    pyds = sorted({path.resolve() for cache_dir in cache_dirs for path in cache_dir.rglob("*.pyd")})
    if not pyds:
        raise RuntimeError("Functional JIT validation produced no .pyd modules")

    unexpected = re.compile(
        r"(?i)(?:python3\d{2}t?(?:_d)?\.dll|libgcc_s[^\s]*\.dll|libstdc\+\+[^\s]*\.dll|"
        r"libwinpthread[^\s]*\.dll|libclang_rt[^\s]*\.dll|clang_rt[^\s]*\.dll|"
        r"libomp[^\s]*\.dll|cygwin1\.dll)"
    )
    report = diagnostics / "pyd-imports.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("", encoding="utf-8")

    for pyd in pyds:
        result = subprocess.run(
            [str(readobj), "--coff-imports", str(pyd)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        text = result.stdout + result.stderr
        with report.open("a", encoding="utf-8") as stream:
            stream.write(f"=== {pyd} ===\n{text}\n")
        if not re.search(r"(?i)python3\.dll", text):
            raise RuntimeError(f"JIT module does not import python3.dll: {pyd}")
        match = unexpected.search(text)
        if match:
            raise RuntimeError(f"JIT module has unexpected compiler/version runtime import {match.group(0)!r}: {pyd}")
    return pyds


def _prove_load_without_toolchain(pyds: list[Path], diagnostics: Path) -> None:
    child = """
import importlib.util
import pathlib
import sys
for raw in sys.argv[1:]:
    path = pathlib.Path(raw)
    name = path.name.split(".", 1)[0]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot create import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    print(f"loaded {path.name}")
"""
    env = os.environ.copy()
    env.pop("FENICS_JIT_ROOT", None)
    env["CC"] = "definitely-missing-cl.exe"
    env["CXX"] = "definitely-missing-cl.exe"
    env["LD"] = "definitely-missing-link.exe"
    env["PATH"] = os.pathsep.join(
        entry
        for entry in env.get("PATH", "").split(os.pathsep)
        if entry
        and "fenics-jit" not in entry.lower()
        and "microsoft visual studio" not in entry.lower()
        and "windows kits" not in entry.lower()
    )
    result = subprocess.run(
        [sys.executable, "-c", child, *[str(path) for path in pyds]],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    (diagnostics / "cache-load-without-toolchain.txt").write_text(result.stdout + result.stderr, encoding="utf-8")


def _serial_validation(cache_root: Path, diagnostics: Path) -> None:
    from petsc4py import PETSc
    from dolfinx import fem, mesh
    from dolfinx.fem.petsc import LinearProblem, assemble_matrix, assemble_vector
    from dolfinx.jit import ffcx_jit

    if " " not in str(Path(sys.prefix)):
        raise RuntimeError(f"Phase 5 install-prefix test requires a path containing spaces: {sys.prefix}")
    if " " not in str(cache_root):
        raise RuntimeError(f"Phase 5 cache test requires a path containing spaces: {cache_root}")

    shutil.rmtree(cache_root, ignore_errors=True)
    cache_root.mkdir(parents=True)
    diagnostics.mkdir(parents=True, exist_ok=True)
    _poison_compiler_environment(diagnostics)
    os.environ["FENICS_JIT_VERBOSE"] = "1"

    record = _runtime_record()
    (diagnostics / "runtime-config.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    form_cache = cache_root / "broad forms cache"
    jit_options = {"cache_dir": form_cache, "cffi_verbose": True}

    with _record_check_calls(diagnostics / "serial-compiler-commands.txt") as calls:
        domain = mesh.create_unit_square(MPI.COMM_SELF, 4, 4)
        tdim = domain.topology.dim
        fdim = tdim - 1
        domain.topology.create_connectivity(fdim, tdim)
        facets = mesh.exterior_facet_indices(domain.topology)

        print("[phase5] P2 Poisson", flush=True)
        V2 = fem.functionspace(domain, ("Lagrange", 2))
        u2, v2 = ufl.TrialFunction(V2), ufl.TestFunction(V2)
        source = fem.Constant(domain, PETSc.ScalarType(1.25))
        a2 = ufl.inner(ufl.grad(u2), ufl.grad(v2)) * ufl.dx
        L2 = source * v2 * ufl.dx
        dofs2 = fem.locate_dofs_topological(V2, fdim, facets)
        bc2 = fem.dirichletbc(PETSc.ScalarType(0), dofs2, V2)
        p2 = LinearProblem(
            a2,
            L2,
            bcs=[bc2],
            petsc_options_prefix="phase5_p2_",
            petsc_options={"ksp_type": "cg", "pc_type": "jacobi", "ksp_rtol": 1e-10},
            jit_options=jit_options,
        )
        uh2 = p2.solve()
        if not np.all(np.isfinite(uh2.x.array)) or np.linalg.norm(uh2.x.array) == 0:
            raise RuntimeError("P2 Poisson solve returned an invalid solution")

        print("[phase5] vector linear elasticity", flush=True)
        Vv = fem.functionspace(domain, ("Lagrange", 1, (2,)))
        u, v = ufl.TrialFunction(Vv), ufl.TestFunction(Vv)
        mu = fem.Constant(domain, PETSc.ScalarType(2.0))
        lam = fem.Constant(domain, PETSc.ScalarType(3.0))

        def eps(w):
            return ufl.sym(ufl.grad(w))

        def sigma(w):
            return 2.0 * mu * eps(w) + lam * ufl.tr(eps(w)) * ufl.Identity(2)

        elasticity = fem.form(ufl.inner(sigma(u), eps(v)) * ufl.dx, jit_options=jit_options)
        A = assemble_matrix(elasticity)
        A.assemble()
        if A.getSize()[0] == 0:
            raise RuntimeError("Elasticity matrix assembly produced an empty matrix")

        print("[phase5] cell/facet integrals and coefficients", flush=True)
        V1 = fem.functionspace(domain, ("Lagrange", 1))
        q = fem.Function(V1)
        q.interpolate(lambda x: x[0] + 2.0 * x[1])
        test = ufl.TestFunction(V1)
        alpha = fem.Constant(domain, PETSc.ScalarType(2.5))
        load = fem.form((q + alpha) * test * ufl.dx + alpha * test * ufl.ds, jit_options=jit_options)
        b = assemble_vector(load)
        if not np.all(np.isfinite(b.array)):
            raise RuntimeError("Cell/facet coefficient assembly produced non-finite values")

        print("[phase5] nonlinear residual and Jacobian", flush=True)
        state = fem.Function(V2)
        state.interpolate(lambda x: 0.1 + x[0] * x[1])
        test2 = ufl.TestFunction(V2)
        direction = ufl.TrialFunction(V2)
        # Standard semilinear Poisson residual. Keep this representative but
        # intentionally compact: the previous quasilinear test triggered an
        # FFCx 0.11 code-generation pathological case before C compilation.
        residual_ufl = (
            ufl.inner(ufl.grad(state), ufl.grad(test2)) * ufl.dx
            + state**3 * test2 * ufl.dx
            - alpha * test2 * ufl.dx
        )
        jacobian_ufl = ufl.derivative(residual_ufl, state, direction)
        residual = fem.form(residual_ufl, jit_options=jit_options)
        jacobian = fem.form(jacobian_ufl, jit_options=jit_options)
        rb = assemble_vector(residual)
        JA = assemble_matrix(jacobian)
        JA.assemble()
        if not np.all(np.isfinite(rb.array)) or JA.getSize()[0] == 0:
            raise RuntimeError("Nonlinear residual/Jacobian validation failed")

        print("[phase5] fem.Expression", flush=True)
        points = np.array([[0.2, 0.2], [0.6, 0.1]], dtype=domain.geometry.x.dtype)
        expr = fem.Expression(alpha * ufl.grad(state), points, jit_options=jit_options)
        ncells = domain.topology.index_map(tdim).size_local
        values = expr.eval(domain, np.arange(ncells, dtype=np.int32))
        if values.size == 0 or not np.all(np.isfinite(values)):
            raise RuntimeError("fem.Expression evaluation failed")

    _assert_compiler_commands(calls, record, require_compile=True)

    print("[phase5] fresh cache and cache reload", flush=True)
    reuse_cache = cache_root / "cache reload proof"
    shutil.rmtree(reuse_cache, ignore_errors=True)
    reuse_cache.mkdir(parents=True)
    domain = mesh.create_unit_square(MPI.COMM_SELF, 2, 2)
    Vr = fem.functionspace(domain, ("Lagrange", 1))
    ur, vr = ufl.TrialFunction(Vr), ufl.TestFunction(Vr)
    cache_form = ufl.inner(ufl.grad(ur), ufl.grad(vr)) * ufl.dx + PETSc.ScalarType(7.125) * ur * vr * ufl.dx
    reuse_options = {"cache_dir": reuse_cache, "cffi_verbose": True}

    with _record_check_calls(diagnostics / "cache-first-commands.txt") as first_calls:
        ffcx_jit(MPI.COMM_SELF, cache_form, jit_options=reuse_options)
    _assert_compiler_commands(first_calls, record, require_compile=True)
    if not list(reuse_cache.rglob("*.pyd")):
        raise RuntimeError("Fresh cache proof produced no JIT .pyd")

    with _record_check_calls(diagnostics / "cache-reload-commands.txt") as reload_calls:
        ffcx_jit(MPI.COMM_SELF, cache_form, jit_options=reuse_options)
    _assert_compiler_commands(reload_calls, record, require_compile=False)
    if reload_calls:
        raise RuntimeError("Cache reload unexpectedly invoked compiler/linker commands: " + "\n".join(reload_calls))

    print("[phase5] PE import and toolchain-free load inspection", flush=True)
    pyds = _inspect_pyds([form_cache, reuse_cache], diagnostics)
    _prove_load_without_toolchain(pyds, diagnostics)

    summary = {
        "mode": "serial",
        "python": sys.version,
        "prefix": sys.prefix,
        "cache_root": str(cache_root),
        "fresh_compiler_commands": len(calls),
        "cache_first_commands": len(first_calls),
        "cache_reload_commands": len(reload_calls),
        "jit_modules": [str(path) for path in pyds],
        "coverage": [
            "P1 Poisson (companion scripts/test-poisson.py)",
            "P2 Poisson",
            "vector linear elasticity",
            "cell integrals",
            "exterior-facet Neumann integrals",
            "Coefficient and Constant",
            "nonlinear residual and Jacobian",
            "fem.Expression",
            "fresh cache and cache reload",
            "PE imports and toolchain-free cache module load",
            "paths containing spaces",
        ],
    }
    (diagnostics / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Phase 5 serial functional validation passed")


def _mpi_validation(cache_root: Path, diagnostics: Path) -> None:
    from petsc4py import PETSc
    from dolfinx import fem, mesh
    from dolfinx.jit import ffcx_jit

    comm = MPI.COMM_WORLD
    if comm.size != 2:
        raise RuntimeError(f"Phase 5 MPI JIT proof requires exactly 2 ranks, got {comm.size}")
    if " " not in str(cache_root):
        raise RuntimeError(f"MPI cache path must contain spaces: {cache_root}")

    if comm.rank == 0:
        shutil.rmtree(cache_root, ignore_errors=True)
        cache_root.mkdir(parents=True)
        diagnostics.mkdir(parents=True, exist_ok=True)
    comm.Barrier()

    _poison_compiler_environment(diagnostics)
    os.environ["FENICS_JIT_VERBOSE"] = "1"
    record = _runtime_record()
    selected = {key: record[key] for key in ("backend", "target", "crt", "clang_reported_target", "toolchain_root", "clang", "python_include", "python_import_library", "ffcx_include")}
    gathered_config = comm.allgather(selected)
    if any(item != gathered_config[0] for item in gathered_config[1:]):
        raise RuntimeError(f"MPI ranks selected different JIT configurations: {gathered_config}")

    if comm.rank == 0:
        print("[phase5] two-rank MPI fresh JIT/cache load", flush=True)
    domain = mesh.create_unit_square(comm, 3, 3)
    V = fem.functionspace(domain, ("Lagrange", 2))
    u, v = ufl.TrialFunction(V), ufl.TestFunction(V)
    beta = fem.Constant(domain, PETSc.ScalarType(4.375))
    # Keep every integral bilinear. Mixing beta * v * ds into this form
    # creates a one-argument integral beside two-argument integrals and UFL
    # correctly rejects the form with ArityMismatch.
    mpi_form = (
        ufl.inner(ufl.grad(u), ufl.grad(v)) * ufl.dx
        + beta * u * v * ufl.dx
        + beta * u * v * ufl.ds
    )
    options = {"cache_dir": cache_root, "cffi_verbose": True}
    command_path = diagnostics / f"mpi-rank-{comm.rank}-compiler-commands.txt"
    with _record_check_calls(command_path) as calls:
        ffcx_jit(comm, mpi_form, jit_options=options)

    _assert_compiler_commands(calls, record, require_compile=comm.rank == 0)
    compile_counts = comm.allgather(len(calls))
    if compile_counts[0] == 0:
        raise RuntimeError("MPI rank 0 did not compile the fresh JIT form")
    if compile_counts[1] != 0:
        raise RuntimeError(f"MPI non-root rank started an independent compile: {compile_counts}")

    comm.Barrier()
    pyds = sorted(cache_root.rglob("*.pyd"))
    visible = comm.allgather([path.name for path in pyds])
    if not visible[0] or any(item != visible[0] for item in visible[1:]):
        raise RuntimeError(f"MPI ranks do not see the same JIT cache artifacts: {visible}")

    rank_record = {"rank": comm.rank, "compile_commands": len(calls), "cache_modules": [str(path) for path in pyds], "configuration": selected}
    (diagnostics / f"mpi-rank-{comm.rank}.json").write_text(json.dumps(rank_record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    comm.Barrier()

    if comm.rank == 0:
        _inspect_pyds([cache_root], diagnostics)
        summary = {"mode": "mpi", "ranks": comm.size, "compile_commands_by_rank": compile_counts, "cache_modules_by_rank": visible, "configuration": gathered_config[0]}
        (diagnostics / "mpi-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("Phase 5 MPI rank-0 compile / rank-1 cache-load validation passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("serial", "mpi"), required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--diagnostics-dir", required=True)
    args = parser.parse_args()
    cache_root = Path(args.cache_dir).resolve()
    diagnostics = Path(args.diagnostics_dir).resolve()
    if args.mode == "serial":
        _serial_validation(cache_root, diagnostics)
    else:
        try:
            _mpi_validation(cache_root, diagnostics)
        except BaseException:
            # DOLFINx\'s mpi_jit protocol can leave peer ranks blocked in a
            # collective when one rank fails before cache publication. Abort
            # the communicator so a test failure is reported immediately
            # instead of waiting for the workflow-level timeout.
            traceback.print_exc()
            sys.stderr.flush()
            try:
                MPI.COMM_WORLD.Abort(1)
            finally:
                os._exit(1)


if __name__ == "__main__":
    main()
