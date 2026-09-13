"""Broad private installed-package qualification for TinyCC Phase 4A.

This script deliberately uses either the existing LLVM-MinGW runtime helper or
the installed TinyCC backend's private adapter. It does not introduce backend
selection or modify production runtime ownership.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pefile
from cffi import FFI

REVISION = "0fb54300b56512754221d80adda85ddb9815bceb"
REQUIRED_DLL_CHARACTERISTICS = 0x40 | 0x20 | 0x100


def load_module(path: Path, name: str):
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


def command_count(diagnostics: Path) -> int:
    path = diagnostics / "compiler-commands.jsonl"
    if not path.is_file():
        return 0
    return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])


def inspect_tinycc_modules(cache: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(cache.rglob("*.pyd")):
        pe = pefile.PE(str(path), fast_load=False)
        imports = sorted(
            entry.dll.decode("ascii", errors="replace").lower()
            for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])
        )
        chars = int(pe.OPTIONAL_HEADER.DllCharacteristics)
        reloc = any(section.Name.rstrip(b"\0") == b".reloc" and section.SizeOfRawData for section in pe.sections)
        pdata = any(section.Name.rstrip(b"\0") == b".pdata" and section.SizeOfRawData for section in pe.sections)
        if "python3.dll" not in imports:
            raise RuntimeError(f"Stable-ABI python3.dll missing from {path}: {imports}")
        if any(name.startswith(("python312", "python313", "python314", "python315")) for name in imports):
            raise RuntimeError(f"minor-version Python import in {path}: {imports}")
        if (chars & REQUIRED_DLL_CHARACTERISTICS) != REQUIRED_DLL_CHARACTERISTICS:
            raise RuntimeError(f"required PE mitigation bits missing from {path}: 0x{chars:x}")
        if not reloc or not pdata:
            raise RuntimeError(f"relocation/unwind metadata missing from {path}: reloc={reloc}, pdata={pdata}")
        records.append(
            {
                "path": str(path),
                "imports": imports,
                "dll_characteristics": chars,
                "reloc": reloc,
                "pdata": pdata,
            }
        )
    if not records:
        raise RuntimeError(f"no generated TinyCC .pyd files found below {cache}")
    return records


def runtime_context(mode: str, backend_root: Path, diagnostics: Path):
    if mode == "tinycc":
        adapter = load_module(backend_root / "tinycc_adapter.py", "phase4a_tinycc_adapter")
        config = adapter.TinyCCConfig.discover(
            root=backend_root,
            python_def=backend_root / "python3.def",
            diagnostics_dir=diagnostics,
            revision=REVISION,
        )
        return adapter.activate(config), config.backend_cache_id

    runtime_path = Path(sys.prefix) / "Library/fenics-jit/runtime/fenics_jit_runtime.py"
    runtime = load_module(runtime_path, "phase4a_llvm_runtime")
    config = runtime.RuntimeConfig.discover(
        toolchain_root=Path(sys.prefix) / "Library/fenics-jit",
        python_prefix=Path(sys.prefix),
    )
    return config.activate(diagnostics_dir=diagnostics), "llvm-mingw-stage-aw-reference"


def assemble_metrics(cache: Path) -> dict[str, float]:
    import ufl
    from dolfinx import fem, mesh
    from mpi4py import MPI

    domain = mesh.create_unit_square(MPI.COMM_WORLD, 6, 5)
    one = fem.Constant(domain, 1.0)
    vector = fem.Constant(domain, np.array([1.25, -0.75], dtype=np.float64))
    tensor = fem.Constant(domain, np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64))
    x = ufl.SpatialCoordinate(domain)

    expressions = {
        "cell_scalar": one * ufl.dx,
        "facet_scalar": one * ufl.ds,
        "vector_cell": ufl.inner(vector, vector) * ufl.dx,
        "tensor_cell": ufl.inner(tensor, tensor) * ufl.dx,
        "coefficient_heavy": (1.3 + 0.7 * x[0] - 0.4 * x[1] + 0.25 * x[0] * x[1]) * ufl.dx,
        "vector_facet": ufl.inner(vector, vector) * ufl.ds,
    }

    values: dict[str, float] = {}
    for name, expression in expressions.items():
        form = fem.form(expression, jit_options={"cache_dir": cache})
        values[name] = float(fem.assemble_scalar(form))

    high = fem.functionspace(domain, ("Lagrange", 2))
    coefficient = fem.Function(high)
    coefficient.interpolate(lambda coords: coords[0] ** 2 + 0.5 * coords[1] ** 2)
    high_form = fem.form(coefficient * coefficient * ufl.dx, jit_options={"cache_dir": cache})
    values["higher_order_p2"] = float(fem.assemble_scalar(high_form))

    expected = {
        "cell_scalar": 1.0,
        "facet_scalar": 4.0,
        "vector_cell": 2.125,
        "tensor_cell": 30.0,
        "coefficient_heavy": 1.5125,
        "vector_facet": 8.5,
        "higher_order_p2": 13.0 / 36.0,
    }
    for name, target in expected.items():
        if not math.isclose(values[name], target, rel_tol=2e-10, abs_tol=2e-10):
            raise RuntimeError(f"{name} numerical result mismatch: got {values[name]}, expected {target}")
    return values


def crt_allocator_stress(backend_root: Path, diagnostics: Path, work: Path) -> Path:
    adapter = load_module(backend_root / "tinycc_adapter.py", "phase4a_crt_adapter")
    config = adapter.TinyCCConfig.discover(
        root=backend_root,
        python_def=backend_root / "python3.def",
        diagnostics_dir=diagnostics,
        revision=REVISION,
    )
    ffi = FFI()
    ffi.cdef("unsigned long long phase4a_crt_stress(int rounds);")
    ffi.set_source(
        "_tinycc_phase4a_crt",
        """
        #include <stdlib.h>
        #include <string.h>
        unsigned long long phase4a_crt_stress(int rounds) {
            unsigned long long total = 0;
            int i;
            for (i = 1; i <= rounds; ++i) {
                size_t n = (size_t)((i % 4093) + 1);
                unsigned char *p = (unsigned char *)malloc(n);
                if (!p) return 0;
                memset(p, i & 255, n);
                total += p[0] + p[n - 1] + (unsigned long long)n;
                free(p);
            }
            return total;
        }
        """,
    )
    build = work / "crt stress build with spaces"
    with adapter.activate(config):
        output = Path(ffi.compile(tmpdir=str(build), verbose=False)).resolve()
    module = load_module(output, "_tinycc_phase4a_crt")
    value = int(module.lib.phase4a_crt_stress(20000))
    if value <= 0:
        raise RuntimeError("mixed-CRT internal allocation stress failed")
    return output


def compare_metrics(actual: dict[str, float], reference_path: Path) -> None:
    reference = json.loads(reference_path.read_text(encoding="utf-8"))["metrics"]
    for name, value in actual.items():
        if name not in reference:
            raise RuntimeError(f"reference metric missing: {name}")
        if not math.isclose(value, float(reference[name]), rel_tol=2e-10, abs_tol=2e-10):
            raise RuntimeError(f"TinyCC/reference mismatch for {name}: {value} != {reference[name]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("llvm-mingw", "tinycc"), required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend-root", type=Path)
    parser.add_argument("--reference-json", type=Path)
    parser.add_argument("--cache-reload", action="store_true")
    args = parser.parse_args()

    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    diagnostics = work / "diagnostics"
    cache = work / "private cache with spaces"
    diagnostics.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    backend_root = (args.backend_root or (Path(sys.prefix) / "Library/fenics-jit/backends/tinycc")).resolve()

    saved_cwd = Path.cwd()
    saved_home = os.environ.get("HOME")
    saved_profile = os.environ.get("USERPROFILE")
    hostile_home = work / "hostile home with spaces"
    hostile_home.mkdir(parents=True, exist_ok=True)
    (work / "setup.cfg").write_text(
        "[build_ext]\ncompiler=msvc\nbuild_temp=forbidden-build-temp\nlibrary_dirs=forbidden-library-root\n",
        encoding="utf-8",
    )
    (hostile_home / "pydistutils.cfg").write_text(
        "[build_ext]\ncompiler=msvc\nbuild_lib=forbidden-build-lib\n",
        encoding="utf-8",
    )

    before = command_count(diagnostics)
    try:
        os.chdir(work)
        if args.mode == "tinycc":
            os.environ["HOME"] = str(hostile_home)
            os.environ["USERPROFILE"] = str(hostile_home)
        manager, backend_cache_id = runtime_context(args.mode, backend_root, diagnostics)
        with manager:
            first = assemble_metrics(cache)
            middle = command_count(diagnostics)
            second = assemble_metrics(cache)
            after_repeat = command_count(diagnostics)
        if first != second:
            raise RuntimeError(f"same-process repeated results changed: {first} != {second}")

        crt_module = None
        if args.mode == "tinycc" and not args.cache_reload:
            crt_module = crt_allocator_stress(backend_root, diagnostics, work)
        after = command_count(diagnostics)
    finally:
        os.chdir(saved_cwd)
        if saved_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = saved_home
        if saved_profile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = saved_profile

    if args.mode == "tinycc":
        commands_path = diagnostics / "compiler-commands.jsonl"
        commands = commands_path.read_text(encoding="utf-8").lower() if commands_path.is_file() else ""
        forbidden = [token for token in ("cl.exe", "link.exe", "clang", "gcc", "vswhere", "windows kits", "microsoft visual studio") if token in commands]
        if forbidden:
            raise RuntimeError(f"forbidden host compiler/SDK input in TinyCC commands: {forbidden}")
        if args.reference_json is None:
            raise RuntimeError("--reference-json is required for TinyCC mode")
        compare_metrics(first, args.reference_json.resolve())
        if args.cache_reload and after != before:
            raise RuntimeError(f"new-process private cache reload unexpectedly compiled: before={before}, after={after}")
        if not args.cache_reload and middle <= before:
            raise RuntimeError(f"fresh TinyCC broad JIT did not invoke compiler: before={before}, first={middle}")
        if after_repeat != middle:
            raise RuntimeError(f"same-process cache reuse unexpectedly compiled: first={middle}, repeat={after_repeat}")
        pe_records = inspect_tinycc_modules(cache)
        if crt_module is not None:
            inspect_tinycc_modules(crt_module.parent)
    else:
        pe_records = []

    result = {
        "status": "pass",
        "mode": args.mode,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "backend_cache_id": backend_cache_id,
        "metrics": first,
        "same_process_repeat": second,
        "compiler_commands_before": before,
        "compiler_commands_after_first_forms": middle,
        "compiler_commands_after_repeat": after_repeat,
        "compiler_commands_after": after,
        "cache_reload": args.cache_reload,
        "generated_modules": pe_records,
        "hostile_config_root": str(work),
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
