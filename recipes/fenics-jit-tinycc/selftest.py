"""Installed-package qualification for the TinyCC FEniCS JIT backend."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pefile
from cffi import FFI

REVISION = "0fb54300b56512754221d80adda85ddb9815bceb"
REQUIRED_DLL_CHARACTERISTICS = 0x40 | 0x20 | 0x100


def load_extension(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inspect_pe(path: Path) -> dict[str, object]:
    pe = pefile.PE(str(path), fast_load=False)
    imports = sorted(
        entry.dll.decode("ascii", errors="replace").lower()
        for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])
    )
    chars = int(pe.OPTIONAL_HEADER.DllCharacteristics)
    if "python3.dll" not in imports:
        raise RuntimeError(f"Stable-ABI python3.dll import missing: {imports}")
    if any(name.startswith(("python312", "python313", "python314", "python315")) for name in imports):
        raise RuntimeError(f"minor-version Python import present: {imports}")
    if (chars & REQUIRED_DLL_CHARACTERISTICS) != REQUIRED_DLL_CHARACTERISTICS:
        raise RuntimeError(f"required PE mitigation bits missing: 0x{chars:x}")
    reloc = any(section.Name.rstrip(b"\0") == b".reloc" and section.SizeOfRawData for section in pe.sections)
    pdata = any(section.Name.rstrip(b"\0") == b".pdata" and section.SizeOfRawData for section in pe.sections)
    if not reloc or not pdata:
        raise RuntimeError(f"PE relocation/unwind metadata missing: reloc={reloc}, pdata={pdata}")
    return {"imports": imports, "dll_characteristics": chars, "reloc": reloc, "pdata": pdata}


def test_activation(adapter, config) -> dict[str, float]:
    from cffi import _shimmed_dist_utils as dist

    original = dist.Distribution
    with adapter.activate(config):
        active = dist.Distribution
        if active is original:
            raise RuntimeError("owned Distribution interception did not activate")
        with adapter.activate(config):
            if dist.Distribution is not active:
                raise RuntimeError("nested activation replaced Distribution")
    if dist.Distribution is not original:
        raise RuntimeError("nested activation did not restore Distribution")

    try:
        with adapter.activate(config):
            raise ValueError("intentional restoration test")
    except ValueError:
        pass
    if dist.Distribution is not original:
        raise RuntimeError("exception path did not restore Distribution")

    entered = threading.Event()
    release = threading.Event()
    second = threading.Event()
    timings: dict[str, float] = {}
    errors: list[BaseException] = []

    def first() -> None:
        try:
            with adapter.activate(config):
                timings["first_enter"] = time.monotonic()
                entered.set()
                if not release.wait(20):
                    raise RuntimeError("serialization release timeout")
                timings["first_exit"] = time.monotonic()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def other() -> None:
        try:
            if not entered.wait(20):
                raise RuntimeError("serialization start timeout")
            timings["second_attempt"] = time.monotonic()
            with adapter.activate(config):
                timings["second_enter"] = time.monotonic()
                second.set()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    a = threading.Thread(target=first)
    b = threading.Thread(target=other)
    a.start(); b.start()
    if not entered.wait(20):
        raise RuntimeError("first activation did not enter")
    time.sleep(0.2)
    if second.is_set():
        raise RuntimeError("second activation interleaved")
    release.set(); a.join(20); b.join(20)
    if a.is_alive() or b.is_alive() or errors:
        raise RuntimeError(f"activation serialization failed: {errors!r}")
    if timings["second_enter"] < timings["first_exit"]:
        raise RuntimeError(f"activation serialization order invalid: {timings}")
    return timings


def test_cffi(adapter, config, work: Path) -> Path:
    ffi = FFI()
    ffi.cdef("int tinycc_package_value(void);")
    ffi.set_source("_tinycc_package_probe", "int tinycc_package_value(void){return 42;}")
    with adapter.activate(config):
        output = Path(ffi.compile(tmpdir=str(work / "cffi build with spaces"), verbose=True)).resolve()
    module = load_extension("_tinycc_package_probe", output)
    if module.lib.tinycc_package_value() != 42:
        raise RuntimeError("installed TinyCC CFFI result mismatch")
    return output


def test_negative_input(adapter, config, work: Path) -> str:
    poison = work / "poison.obj"
    poison.write_bytes(b"not-an-object")
    ffi = FFI()
    ffi.cdef("int x(void);")
    ffi.set_source("_tinycc_package_negative", "int x(void){return 1;}", extra_objects=[str(poison)])
    try:
        with adapter.activate(config):
            ffi.compile(tmpdir=str(work / "negative"), verbose=False)
    except Exception as exc:  # noqa: BLE001
        if "rejects extra object" not in str(exc):
            raise
        return str(exc)
    raise RuntimeError("foreign object input was silently accepted")


def test_abi_model(backend: Path, work: Path) -> dict[str, int]:
    source = work / "abi-model.c"
    exe = work / "abi-model.exe"
    source.write_text(
        "#include <stdio.h>\n"
        "struct bits { unsigned a:3; unsigned b:5; unsigned c:8; };\n"
        "int main(void){ struct bits x={5,17,171}; const unsigned char *p=(const unsigned char *)&x; "
        "unsigned raw=(unsigned)p[0]|((unsigned)p[1]<<8)|((unsigned)p[2]<<16)|((unsigned)p[3]<<24); "
        "printf(\"%zu %zu %zu %u\\n\",sizeof(long double),_Alignof(long double),sizeof(x),raw); return 0;}\n",
        encoding="ascii",
    )
    subprocess.run(
        [str(backend / "tcc.exe"), "-B" + str(backend), "-mms-bitfields", str(source), "-o", str(exe)],
        check=True,
        cwd=work,
    )
    values = subprocess.check_output([str(exe)], text=True).strip().split()
    result = {"sizeof_long_double": int(values[0]), "alignof_long_double": int(values[1]), "bitfield_size": int(values[2]), "bitfield_raw": int(values[3])}
    if result != {"sizeof_long_double": 8, "alignof_long_double": 8, "bitfield_size": 4, "bitfield_raw": 43917}:
        raise RuntimeError(f"installed TinyCC ABI policy mismatch: {result}")
    return result


def run_poisson(adapter, config, work: Path) -> dict[str, float]:
    import basix.ufl
    import numpy as np
    import ufl
    from dolfinx import fem, mesh
    from dolfinx.fem.petsc import LinearProblem
    from mpi4py import MPI

    domain = mesh.create_unit_square(MPI.COMM_WORLD, 8, 8)
    space = fem.functionspace(domain, ("Lagrange", 1))
    fdim = domain.topology.dim - 1
    facets = mesh.locate_entities_boundary(domain, fdim, lambda x: np.full(x.shape[1], True, dtype=bool))
    bc = fem.dirichletbc(0.0, fem.locate_dofs_topological(space, fdim, facets), space)
    u = ufl.TrialFunction(space); v = ufl.TestFunction(space)
    cache = work / "ffcx-cache"
    cache.mkdir(parents=True, exist_ok=True)
    with adapter.activate(config):
        problem = LinearProblem(
            ufl.inner(ufl.grad(u), ufl.grad(v)) * ufl.dx,
            fem.Constant(domain, 1.0) * v * ufl.dx,
            bcs=[bc],
            petsc_options={"ksp_type": "preonly", "pc_type": "lu"},
            petsc_options_prefix="tinycc_package_",
            jit_options={"cache_dir": cache},
        )
        solution = problem.solve()
        norm = float(np.linalg.norm(solution.x.array))
    if not np.isfinite(norm) or norm <= 0:
        raise RuntimeError(f"Poisson solution norm invalid: {norm}")
    return {"solution_norm": norm, "generated_pyd_count": float(len(list(cache.rglob("*.pyd"))))}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-root", type=Path)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--poisson", action="store_true")
    args = parser.parse_args()

    backend = (args.backend_root or (Path(sys.prefix) / "Library/fenics-jit/backends/tinycc")).resolve()
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    for required in ("tcc.exe", "libtcc.dll", "python3.def", "tinycc_adapter.py", "backend-metadata.json"):
        if not (backend / required).is_file():
            raise RuntimeError(f"installed backend file missing: {required}")
    if (Path(sys.prefix) / "Library/fenics-jit/runtime/fenics_jit_runtime.py").is_file() and "fenics-jit-tinycc" in str(backend):
        # The runtime file may be owned by the production LLVM package in a full FEniCS env;
        # ownership is checked from the package manifest by Phase-3 comparison, not by prefix existence.
        pass

    metadata = json.loads((backend / "backend-metadata.json").read_text(encoding="utf-8"))
    sys.path.insert(0, str(backend))
    import tinycc_adapter as adapter

    config = adapter.TinyCCConfig.discover(
        root=backend,
        python_def=backend / "python3.def",
        diagnostics_dir=work / "diagnostics",
        revision=REVISION,
    )
    if config.backend_cache_id != metadata["backend_cache_id"]:
        raise RuntimeError("packaged backend cache identity does not match adapter policy")

    timings = test_activation(adapter, config)
    extension = test_cffi(adapter, config, work)
    pe = inspect_pe(extension)
    negative = test_negative_input(adapter, config, work)
    abi = test_abi_model(backend, work)
    poisson = run_poisson(adapter, config, work) if args.poisson else None

    commands = (work / "diagnostics" / "compiler-commands.jsonl").read_text(encoding="utf-8").lower()
    forbidden = [token for token in ("cl.exe", "link.exe", "clang", "gcc", "windows kits", "microsoft visual studio") if token in commands]
    if forbidden:
        raise RuntimeError(f"forbidden host compiler input recorded by installed adapter: {forbidden}")

    summary = {
        "status": "pass",
        "backend_root_name": backend.name,
        "backend_cache_id": config.backend_cache_id,
        "metadata_sha256": hashlib.sha256((backend / "backend-metadata.json").read_bytes()).hexdigest(),
        "extension": str(extension),
        "pe": pe,
        "abi": abi,
        "negative_input": negative,
        "activation_serialization": timings,
        "poisson": poisson,
    }
    (work / "phase3-selftest.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
