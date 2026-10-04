"""Two-rank proof for the implicit micro-Clang Windows JIT default."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

import ufl
from dolfinx import fem, mesh
from dolfinx.jit import ffcx_jit
from mpi4py import MPI


def load_selector():
    path = Path(sys.prefix) / "Library/fenics-jit/runtime/fenics_jit_selector.py"
    spec = importlib.util.spec_from_file_location("_default_mpi_selector", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load selector: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def record_commands():
    calls = []
    original = subprocess.check_call

    def logged(cmd, *args, **kwargs):
        calls.append(
            subprocess.list2cmdline([str(part) for part in cmd])
            if isinstance(cmd, (list, tuple))
            else str(cmd)
        )
        return original(cmd, *args, **kwargs)

    subprocess.check_call = logged
    try:
        yield calls
    finally:
        subprocess.check_call = original


def main() -> int:
    comm = MPI.COMM_WORLD
    if comm.size != 2:
        raise RuntimeError(f"default MPI proof requires two ranks, got {comm.size}")
    if os.environ.get("FENICS_JIT_COMPILER"):
        raise RuntimeError("default MPI proof requires FENICS_JIT_COMPILER unset")

    selector = load_selector()
    runtime = selector.discover_runtime()
    if runtime.selected_backend != "micro-clang":
        raise RuntimeError(f"implicit selector chose {runtime.selected_backend!r}")

    # Poison ambient compiler/SDK state on both ranks. The package-owned
    # micro-Clang path must still be selected.
    poison = Path(os.environ.get("TEMP", ".")) / "default-mpi-poison"
    os.environ.update(
        {
            "CC": "definitely-missing-cl.exe",
            "CXX": "definitely-missing-cl.exe",
            "LD": "definitely-missing-link.exe",
            "VSINSTALLDIR": str(poison / "Microsoft Visual Studio"),
            "WindowsSdkDir": str(poison / "Windows Kits"),
            "INCLUDE": str(poison / "include"),
            "LIB": str(poison / "lib"),
        }
    )

    cache = Path(sys.argv[1]).resolve()
    if comm.rank == 0:
        shutil.rmtree(cache, ignore_errors=True)
        cache.mkdir(parents=True)
    comm.Barrier()

    domain = mesh.create_unit_square(comm, 3, 3)
    V = fem.functionspace(domain, ("Lagrange", 2))
    u, v = ufl.TrialFunction(V), ufl.TestFunction(V)
    beta = fem.Constant(domain, 4.375)
    form = (
        ufl.inner(ufl.grad(u), ufl.grad(v)) * ufl.dx
        + beta * u * v * ufl.dx
        + beta * u * v * ufl.ds
    )

    with record_commands() as calls:
        ffcx_jit(comm, form, jit_options={"cache_dir": cache, "cffi_verbose": True})

    rendered = "\n".join(calls).lower()
    if comm.rank == 0:
        if "x86_64-w64-mingw32-clang.exe" not in rendered:
            raise RuntimeError("MPI compile owner did not invoke packaged micro-Clang")
        if str(runtime.backend_root).lower() not in rendered:
            raise RuntimeError("MPI compile owner did not use micro-Clang backend root")
    elif calls:
        raise RuntimeError(f"non-root rank independently invoked compiler: {calls}")

    counts = comm.allgather(len(calls))
    modules = comm.allgather(sorted(path.name for path in cache.rglob("*.pyd")))
    if counts[0] == 0 or counts[1] != 0:
        raise RuntimeError(f"unexpected compile ownership: {counts}")
    if not modules[0] or modules[0] != modules[1]:
        raise RuntimeError(f"ranks do not share the same cache modules: {modules}")
    if os.environ.get("FENICS_JIT_COMPILER"):
        raise RuntimeError("selector activation did not restore the unset selector")

    if comm.rank == 0:
        print(
            json.dumps(
                {
                    "status": "pass",
                    "selected_backend": runtime.selected_backend,
                    "backend_cache_id": runtime.backend_cache_id,
                    "compile_commands_by_rank": counts,
                    "cache_modules_by_rank": modules,
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException:
        traceback.print_exc()
        sys.stderr.flush()
        sys.stdout.flush()
        if MPI.COMM_WORLD.size > 1:
            try:
                MPI.COMM_WORLD.Abort(1)
            finally:
                os._exit(1)
        raise
