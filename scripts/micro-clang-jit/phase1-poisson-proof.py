"""Run the Poisson proof through the private micro-Clang activation path.

This deliberately bypasses the production DOLFINx shared selector. Phase 1 is
required to qualify the source-built compiler before adding a production
selector entry.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import os
import runpy
import subprocess
import sys
from pathlib import Path


def load_runtime(toolchain_root: Path):
    path = toolchain_root / "runtime" / "fenics_jit_runtime.py"
    spec = importlib.util.spec_from_file_location("_micro_clang_private_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load private JIT runtime: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def private_outer_runtime(_jit_options):
    """Keep DOLFINx inside the already-active private Phase-1 compiler."""
    yield


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poisson-script", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--diagnostics-dir", required=True)
    parser.add_argument("--toolchain-root", required=True)
    parser.add_argument("--python-prefix", required=True)
    args = parser.parse_args()

    poisson_script = Path(args.poisson_script).resolve()
    cache_dir = Path(args.cache_dir).resolve()
    diagnostics = Path(args.diagnostics_dir).resolve()
    toolchain_root = Path(args.toolchain_root).resolve()
    python_prefix = Path(args.python_prefix).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    diagnostics.mkdir(parents=True, exist_ok=True)

    (cache_dir / "setup.cfg").write_text(
        "[build_ext]\n"
        "compiler = msvc\n"
        "include_dirs = C:\\\\poison\\\\Microsoft Visual Studio\\\\include\n"
        "library_dirs = C:\\\\poison\\\\Windows Kits\\\\lib\n",
        encoding="utf-8",
    )

    runtime = load_runtime(toolchain_root)
    config = runtime.RuntimeConfig.discover(
        toolchain_root=toolchain_root,
        python_prefix=python_prefix,
    )
    command_log = diagnostics / "compiler-commands.txt"
    original_check_call = subprocess.check_call

    with config.activate(diagnostics_dir=diagnostics, verbose=True):
        os.environ["XDG_CACHE_HOME"] = str(cache_dir.parent)

        import cffi
        import dolfinx
        import dolfinx.jit
        import ffcx
        import setuptools
        from cffi._shimmed_dist_utils import Distribution

        (diagnostics / "versions.txt").write_text(
            "\n".join(
                [
                    f"dolfinx={dolfinx.__version__}",
                    f"ffcx={ffcx.__version__}",
                    f"cffi={cffi.__version__}",
                    f"setuptools={setuptools.__version__}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        dist = Distribution()
        dist.parse_config_files()
        option = dist.get_option_dict("build_ext").get("compiler")
        compiler = option[1] if option else None
        (diagnostics / "setuptools-compiler.txt").write_text(str(compiler), encoding="utf-8")
        if compiler != "mingw32":
            raise RuntimeError(f"private runtime did not select mingw32: {compiler!r}")

        # Newer repository builds wrap each local FFCx JIT operation in the
        # production Windows selector. Phase 1 must neutralize that wrapper so
        # it cannot reactivate the installed LLVM-MinGW backend. Older channel
        # builds predate the selector hook; in that case the already-active
        # private runtime directly governs FFCx/CFFI and no patch is required.
        original_dolfinx_context = getattr(
            dolfinx.jit, "_fenics_windows_jit_runtime", None
        )
        if original_dolfinx_context is not None:
            dolfinx.jit._fenics_windows_jit_runtime = private_outer_runtime

        def logged_check_call(cmd, *call_args, **call_kwargs):
            rendered = subprocess.list2cmdline([str(part) for part in cmd])
            with command_log.open("a", encoding="utf-8") as stream:
                stream.write(rendered + "\n")
            return original_check_call(cmd, *call_args, **call_kwargs)

        subprocess.check_call = logged_check_call
        try:
            runpy.run_path(str(poisson_script), run_name="__main__")
        finally:
            subprocess.check_call = original_check_call
            if original_dolfinx_context is not None:
                dolfinx.jit._fenics_windows_jit_runtime = original_dolfinx_context

    pyds = sorted(cache_dir.glob("*.pyd"))
    if not pyds:
        raise RuntimeError(f"fresh Poisson solve produced no JIT .pyd files in {cache_dir}")
    (diagnostics / "pyd-paths.txt").write_text(
        "".join(f"{path}\n" for path in pyds),
        encoding="utf-8",
    )
    print(f"fresh private micro-Clang JIT modules: {len(pyds)}")


if __name__ == "__main__":
    main()
