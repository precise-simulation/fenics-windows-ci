"""Run the qualified Phase-4A proof plus Phase-4B shared JIT concurrency evidence."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def argument_value(name: str) -> str | None:
    try:
        index = sys.argv.index(name)
    except ValueError:
        return None
    if index + 1 >= len(sys.argv):
        raise RuntimeError(f"missing value for {name}")
    return sys.argv[index + 1]


def main() -> int:
    scripts = Path(__file__).resolve().parent
    core = scripts / "phase4a-proof-core.py"
    completed = subprocess.run([sys.executable, str(core), *sys.argv[1:]], check=False)
    if completed.returncode != 0:
        return completed.returncode

    if argument_value("--mode") != "llvm-mingw":
        return 0

    work_value = argument_value("--work-dir")
    output_value = argument_value("--output")
    if work_value is None or output_value is None:
        raise RuntimeError("LLVM-MinGW qualification requires --work-dir and --output")

    output = Path(output_value).resolve()
    if output.name.startswith("reference-"):
        concurrency_name = "concurrency-" + output.name[len("reference-") :]
    else:
        concurrency_name = f"{output.stem}-concurrency{output.suffix}"

    concurrency = scripts / "phase4b-concurrency-proof.py"
    concurrency_run = subprocess.run(
        [
            sys.executable,
            str(concurrency),
            "--work-dir",
            str(Path(work_value).resolve() / "shared JIT concurrency with spaces"),
            "--output",
            str(output.with_name(concurrency_name)),
        ],
        check=False,
    )
    return concurrency_run.returncode


if __name__ == "__main__":
    raise SystemExit(main())
