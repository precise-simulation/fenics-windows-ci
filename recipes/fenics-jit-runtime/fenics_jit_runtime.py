"""Backend-neutral compatibility loader for packaged FEniCS JIT runtimes.

The shared runtime owns this stable import path. Compiler-specific runtime
implementations live below Library/fenics-jit/backends/<backend> and are loaded
only after the caller has selected an installed backend.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType


def _default_backend_root() -> Path:
    return (Path(__file__).resolve().parent.parent / "backends" / "llvm-mingw").resolve()


def _load_backend_runtime(toolchain_root: str | os.PathLike[str] | None = None) -> tuple[Path, ModuleType]:
    root = Path(toolchain_root).resolve() if toolchain_root is not None else _default_backend_root()
    path = root / "fenics_jit_runtime.py"
    if not path.is_file():
        raise RuntimeError(
            "Selected FEniCS JIT backend runtime is missing. Expected "
            f"{path}; install the corresponding compiler backend package."
        )

    module_name = "_fenics_jit_backend_runtime_" + str(abs(hash(str(path))))
    module = sys.modules.get(module_name)
    if module is None:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load FEniCS JIT backend runtime: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(module_name, None)
            raise
    return root, module


class RuntimeConfig:
    """Compatibility facade delegating discovery to the selected backend root."""

    @classmethod
    def discover(
        cls,
        *,
        toolchain_root: str | os.PathLike[str] | None = None,
        **kwargs,
    ):
        root, module = _load_backend_runtime(toolchain_root)
        backend_config = getattr(module, "RuntimeConfig", None)
        if backend_config is None:
            raise RuntimeError(f"Backend runtime below {root} does not expose RuntimeConfig")
        return backend_config.discover(toolchain_root=root, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--toolchain-root")
    parser.add_argument("--python-prefix")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    config = RuntimeConfig.discover(
        toolchain_root=args.toolchain_root,
        python_prefix=args.python_prefix,
    )
    record = config.diagnostic_record()
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
    else:
        print(
            f"LLVM-MinGW / {record['clang_version']} / {config.backend} / "
            f"{record['clang_reported_target']} / {config.crt}"
        )
        print(f"Python: {config.python_include} / {config.python_dll.name}")


if __name__ == "__main__":
    main()
