"""Run the repository Poisson test while recording FFCx/CFFI compiler commands."""

from __future__ import annotations

import argparse
import os
import runpy
import subprocess
from pathlib import Path

from cffi._shimmed_dist_utils import Distribution


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poisson-script", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--diagnostics-dir", required=True)
    args = parser.parse_args()

    poisson_script = Path(args.poisson_script).resolve()
    cache_dir = Path(args.cache_dir).resolve()
    diagnostics = Path(args.diagnostics_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    diagnostics.mkdir(parents=True, exist_ok=True)

    if not poisson_script.is_file():
        raise RuntimeError(f"Poisson script not found: {poisson_script}")

    setup_cfg = cache_dir / "setup.cfg"
    setup_cfg.write_text("[build_ext]\ncompiler = mingw32\n", encoding="utf-8")

    previous_cwd = Path.cwd()
    try:
        os.chdir(cache_dir)
        dist = Distribution()
        dist.parse_config_files()
        option = dist.get_option_dict("build_ext").get("compiler")
        compiler = option[1] if option else None
    finally:
        os.chdir(previous_cwd)

    (diagnostics / "setuptools-compiler.txt").write_text(str(compiler), encoding="utf-8")
    if compiler != "mingw32":
        raise RuntimeError(f"FFCx cache setup.cfg did not select mingw32; got {compiler!r}")

    command_log = diagnostics / "compiler-commands.txt"
    original_check_call = subprocess.check_call

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

    pyds = sorted(cache_dir.glob("*.pyd"))
    if not pyds:
        raise RuntimeError(f"Fresh Poisson solve produced no JIT .pyd files in {cache_dir}")

    (diagnostics / "pyd-paths.txt").write_text(
        "".join(f"{path}\n" for path in pyds), encoding="utf-8"
    )
    print(f"setuptools compiler: {compiler}")
    print(f"fresh JIT modules: {len(pyds)}")


if __name__ == "__main__":
    main()
