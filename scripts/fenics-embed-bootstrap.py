"""Relocatability bootstrap for the FEniCS Windows embedded-runtime overlay."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_DLL_HANDLES: list[object] = []
_ACTIVATED_ROOT: Path | None = None


def _prepend_process_path(path: Path) -> None:
    current = os.environ.get("PATH", "")
    parts = [item for item in current.split(os.pathsep) if item]
    normalized = {os.path.normcase(os.path.abspath(item)) for item in parts}
    candidate = os.path.normcase(os.path.abspath(str(path)))
    if candidate not in normalized:
        os.environ["PATH"] = str(path) + (os.pathsep + current if current else "")


def activate(runtime_root: str | os.PathLike[str] | None = None) -> Path:
    """Activate the bundled Windows FEniCS runtime exactly once."""

    global _ACTIVATED_ROOT

    if os.name != "nt":
        raise RuntimeError("fenics_embed_runtime is Windows-only")
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError(
            f"FEniCS embedded runtime requires CPython 3.12, got {sys.version_info.major}.{sys.version_info.minor}"
        )

    root = Path(runtime_root if runtime_root is not None else sys.prefix).resolve()
    library = root / "Library"
    library_bin = library / "bin"
    jit_root = library / "fenics-jit"

    for required, label in (
        (library_bin, "FEniCS native DLL directory"),
        (jit_root / "runtime" / "fenics_jit_selector.py", "FEniCS JIT selector"),
        (jit_root / "backends" / "micro-clang", "micro-Clang JIT backend"),
    ):
        if not required.exists():
            raise RuntimeError(f"{label} is missing from embedded runtime: {required}")

    if _ACTIVATED_ROOT is not None:
        if _ACTIVATED_ROOT != root:
            raise RuntimeError(
                f"FEniCS embedded runtime already activated from {_ACTIVATED_ROOT}; cannot switch to {root}"
            )
        return root

    _DLL_HANDLES.append(os.add_dll_directory(str(library_bin)))
    _prepend_process_path(library_bin)

    os.environ["FENICS_JIT_ROOT"] = str(jit_root)

    petsc_root = library
    os.environ["PETSC_DIR"] = str(petsc_root)

    import petsc4py

    original_get_config = petsc4py.get_config
    if not getattr(original_get_config, "_fenics_embed_runtime", False):

        def relocated_get_config(
            _original=original_get_config,
            _petsc_root=str(petsc_root),
        ):
            config = dict(_original())
            config["PETSC_DIR"] = _petsc_root
            return config

        relocated_get_config._fenics_embed_runtime = True
        petsc4py.get_config = relocated_get_config

    _ACTIVATED_ROOT = root
    return root
