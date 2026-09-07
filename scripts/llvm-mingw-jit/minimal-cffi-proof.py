"""Minimal CFFI compile/load proof for the LLVM-MinGW Windows JIT experiment."""

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path

from cffi import FFI
from cffi._shimmed_dist_utils import Distribution


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--diagnostics-dir", required=True)
    parser.add_argument("--python-lib-dir", required=True)
    args = parser.parse_args()

    work_dir = Path(args.work_dir).resolve()
    diagnostics_dir = Path(args.diagnostics_dir).resolve()
    python_lib_dir = Path(args.python_lib_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    setup_cfg = work_dir / "setup.cfg"
    setup_cfg.write_text("[build_ext]\ncompiler = mingw32\n", encoding="utf-8")

    previous_cwd = Path.cwd()
    try:
        os.chdir(work_dir)

        dist = Distribution()
        dist.parse_config_files()
        option = dist.get_option_dict("build_ext").get("compiler")
        compiler = option[1] if option else None
        (diagnostics_dir / "setuptools-compiler.txt").write_text(
            str(compiler), encoding="utf-8"
        )
        if compiler != "mingw32":
            raise RuntimeError(
                f"JIT-local setup.cfg did not select mingw32; got {compiler!r}"
            )

        ffi = FFI()
        ffi.cdef("int add_ints(int a, int b);")
        ffi.set_source(
            "_llvm_mingw_cffi_probe",
            "int add_ints(int a, int b) { return a + b; }",
            extra_compile_args=["-std=c17"],
            library_dirs=[str(python_lib_dir)],
        )
        output = Path(ffi.compile(tmpdir=str(work_dir), verbose=True)).resolve()
    finally:
        os.chdir(previous_cwd)

    spec = importlib.util.spec_from_file_location("_llvm_mingw_cffi_probe", output)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot create import spec for {output}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.lib.add_ints(19, 23)
    if result != 42:
        raise RuntimeError(f"Compiled CFFI extension returned {result}, expected 42")

    (diagnostics_dir / "pyd-path.txt").write_text(str(output), encoding="utf-8")
    print(f"setuptools compiler: {compiler}")
    print(f"compiled extension: {output}")
    print(f"add_ints(19, 23) = {result}")


if __name__ == "__main__":
    main()
