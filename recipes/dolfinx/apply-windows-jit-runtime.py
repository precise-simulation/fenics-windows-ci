#!/usr/bin/env python3
"""Patch DOLFINx's Windows JIT entry point to use fenics-jit-llvm-mingw."""

from __future__ import annotations

import sys
from pathlib import Path

MARKER = "_fenics_windows_jit_runtime"


def patch(source_root: Path) -> Path:
    path = source_root / "python" / "dolfinx" / "jit.py"
    text = path.read_text(encoding="utf-8")

    if MARKER in text:
        print(f"Windows JIT runtime patch already present: {path}")
        return path

    imports_old = """import functools
import json
import os
import sys
from pathlib import Path
"""
    imports_new = """import contextlib
import functools
import importlib.util
import json
import os
import sys
from pathlib import Path
"""
    if imports_old not in text:
        raise RuntimeError(f"Could not find DOLFINx JIT import block in {path}")
    text = text.replace(imports_old, imports_new, 1)

    insertion_anchor = "\n\ndef mpi_jit_decorator(local_jit, *args, **kwargs):\n"
    helper = r'''

@functools.cache
def _load_fenics_windows_jit_runtime():
    """Load the packaged Windows JIT helper without requiring PYTHONPATH."""
    if not sys.platform.startswith("win32"):
        return None

    configured_root = os.getenv("FENICS_JIT_ROOT")
    root = (
        Path(configured_root)
        if configured_root
        else Path(sys.prefix) / "Library" / "fenics-jit"
    )
    helper_path = root / "runtime" / "fenics_jit_runtime.py"
    if not helper_path.is_file():
        raise RuntimeError(
            "FEniCS Windows JIT runtime is missing. Expected "
            f"{helper_path}; install fenics-jit-llvm-mingw."
        )

    module_name = "_fenics_windows_jit_runtime"
    module = sys.modules.get(module_name)
    if module is None:
        spec = importlib.util.spec_from_file_location(module_name, helper_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load FEniCS Windows JIT runtime: {helper_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def _fenics_windows_jit_runtime():
    """Activate the packaged compiler only around one local JIT operation."""
    if not sys.platform.startswith("win32"):
        yield
        return

    runtime = _load_fenics_windows_jit_runtime()
    config = runtime.RuntimeConfig.discover()
    verbose = os.getenv("FENICS_JIT_VERBOSE", "").lower() in {"1", "true", "yes", "on"}
    with config.activate(verbose=verbose):
        yield
'''
    if insertion_anchor not in text:
        raise RuntimeError(f"Could not find DOLFINx JIT insertion point in {path}")
    text = text.replace(insertion_anchor, helper + insertion_anchor, 1)

    compile_old = """    # Switch on type and compile, returning cffi object
    if isinstance(ufl_object, ufl.Form):
        r = ffcx.codegeneration.jit.compile_forms([ufl_object], options=p_ffcx, **p_jit)
    elif isinstance(ufl_object, tuple) and isinstance(ufl_object[0], ufl.core.expr.Expr):
        r = ffcx.codegeneration.jit.compile_expressions([ufl_object], options=p_ffcx, **p_jit)
    else:
        raise TypeError(type(ufl_object))

    return (r[0][0], r[1], r[2])
"""
    compile_new = """    # Switch on type and compile, returning cffi object. On Windows the
    # packaged runtime helper owns compiler/backend/include/library selection.
    with _fenics_windows_jit_runtime():
        if isinstance(ufl_object, ufl.Form):
            r = ffcx.codegeneration.jit.compile_forms([ufl_object], options=p_ffcx, **p_jit)
        elif isinstance(ufl_object, tuple) and isinstance(ufl_object[0], ufl.core.expr.Expr):
            r = ffcx.codegeneration.jit.compile_expressions([ufl_object], options=p_ffcx, **p_jit)
        else:
            raise TypeError(type(ufl_object))

    return (r[0][0], r[1], r[2])
"""
    if compile_old not in text:
        raise RuntimeError(f"Could not find DOLFINx FFCx compile block in {path}")
    text = text.replace(compile_old, compile_new, 1)

    path.write_text(text, encoding="utf-8")
    print(f"Applied Windows LLVM-MinGW JIT runtime patch: {path}")
    return path


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-windows-jit-runtime.py <dolfinx-source-root>")
    patch(Path(sys.argv[1]).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
