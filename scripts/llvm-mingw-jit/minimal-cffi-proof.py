"""Minimal CFFI compile/load proof using the packaged FEniCS JIT runtime helper."""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path


def _load_runtime(toolchain_root: Path):
    path = toolchain_root / "runtime" / "fenics_jit_runtime.py"
    spec = importlib.util.spec_from_file_location("fenics_jit_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load packaged JIT runtime helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--diagnostics-dir", required=True)
    parser.add_argument("--toolchain-root", required=True)
    parser.add_argument("--python-prefix", required=True)
    args = parser.parse_args()

    work_dir = Path(args.work_dir).resolve()
    diagnostics_dir = Path(args.diagnostics_dir).resolve()
    toolchain_root = Path(args.toolchain_root).resolve()
    python_prefix = Path(args.python_prefix).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    # Deliberately poison the config file CFFI/setuptools would normally parse.
    # The runtime helper must ignore this and select mingw32 programmatically.
    (work_dir / "setup.cfg").write_text(
        "[build_ext]\n"
        "compiler = msvc\n"
        "include_dirs = C:\\\\poison\\\\Microsoft Visual Studio\\\\include\n"
        "library_dirs = C:\\\\poison\\\\Windows Kits\\\\lib\n",
        encoding="utf-8",
    )

    runtime = _load_runtime(toolchain_root)
    config = runtime.RuntimeConfig.discover(
        toolchain_root=toolchain_root,
        python_prefix=python_prefix,
    )

    previous_cwd = Path.cwd()
    command_log = diagnostics_dir / "compiler-commands.txt"
    compiler = None
    output: Path | None = None
    result = None

    with config.activate(diagnostics_dir=diagnostics_dir, verbose=True):
        from cffi import FFI
        from cffi._shimmed_dist_utils import Distribution

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
                    f"Runtime helper did not select mingw32; got {compiler!r}"
                )

            original_check_call = subprocess.check_call

            def logged_check_call(cmd, *call_args, **call_kwargs):
                rendered = subprocess.list2cmdline([str(part) for part in cmd])
                with command_log.open("a", encoding="utf-8") as stream:
                    stream.write(rendered + "\n")
                return original_check_call(cmd, *call_args, **call_kwargs)

            subprocess.check_call = logged_check_call
            try:
                ffi = FFI()
                ffi.cdef("int add_ints(int a, int b);")
                ffi.set_source(
                    "_llvm_mingw_cffi_probe",
                    "int add_ints(int a, int b) { return a + b; }",
                    extra_compile_args=["-std=c17"],
                )
                output = Path(
                    ffi.compile(tmpdir=str(work_dir), verbose=True)
                ).resolve()
            finally:
                subprocess.check_call = original_check_call
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

    assert output is not None
    (diagnostics_dir / "pyd-path.txt").write_text(str(output), encoding="utf-8")
    print(f"setuptools compiler: {compiler}")
    print(f"compiled extension: {output}")
    print(f"add_ints(19, 23) = {result}")


if __name__ == "__main__":
    main()
