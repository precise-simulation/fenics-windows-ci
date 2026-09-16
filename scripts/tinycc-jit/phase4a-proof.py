"""Run Phase-4A/4B qualification plus the fresh TinyCC Phase-5 corpus."""

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


def evidence_name(output: Path, prefix: str) -> str:
    if output.name.startswith("reference-"):
        return prefix + output.name[len("reference-") :]
    return f"{output.stem}-{prefix.rstrip('-')}{output.suffix}"


def main() -> int:
    scripts = Path(__file__).resolve().parent
    core = scripts / "phase4a-proof-core.py"
    completed = subprocess.run([sys.executable, str(core), *sys.argv[1:]], check=False)
    if completed.returncode != 0:
        return completed.returncode

    mode = argument_value("--mode")
    if mode == "tinycc":
        if "--cache-reload" in sys.argv:
            return 0

        work_value = argument_value("--work-dir")
        output_value = argument_value("--output")
        if work_value is None or output_value is None:
            raise RuntimeError("fresh TinyCC qualification requires --work-dir and --output")

        work = Path(work_value).resolve()
        output = Path(output_value).resolve()
        phase5 = scripts / "phase5-functional-validation.py"
        phase5_run = subprocess.run(
            [
                sys.executable,
                str(phase5),
                "--cache-dir",
                str(work / "p5 integrated cache"),
                "--diagnostics-dir",
                str(output.parent / f"{output.stem}-phase5"),
            ],
            check=False,
        )
        if phase5_run.returncode != 0:
            return phase5_run.returncode

        phase5_mpi = scripts / "phase5-mpi-functional-validation.py"
        mpi_run = subprocess.run(
            [
                sys.executable,
                str(phase5_mpi),
                "--cache-dir",
                str(work / "p5 mpi cache"),
                "--diagnostics-dir",
                str(output.parent / f"{output.stem}-phase5-mpi"),
            ],
            check=False,
        )
        return mpi_run.returncode

    if mode != "llvm-mingw":
        return 0

    work_value = argument_value("--work-dir")
    output_value = argument_value("--output")
    if work_value is None or output_value is None:
        raise RuntimeError("LLVM-MinGW qualification requires --work-dir and --output")

    work = Path(work_value).resolve()
    output = Path(output_value).resolve()

    concurrency = scripts / "phase4b-concurrency-proof.py"
    concurrency_run = subprocess.run(
        [
            sys.executable,
            str(concurrency),
            "--work-dir",
            str(work / "p4bc"),
            "--output",
            str(output.with_name(evidence_name(output, "concurrency-"))),
        ],
        check=False,
    )
    if concurrency_run.returncode != 0:
        return concurrency_run.returncode

    mpi = scripts / "phase4b-mpi-proof.py"
    mpi_run = subprocess.run(
        [
            sys.executable,
            str(mpi),
            "--work-dir",
            str(work / "p4bm"),
            "--output",
            str(output.with_name(evidence_name(output, "mpi-"))),
        ],
        check=False,
    )
    if mpi_run.returncode != 0:
        return mpi_run.returncode

    regression = scripts / "phase4b-llvm-regression-proof.py"
    regression_run = subprocess.run(
        [
            sys.executable,
            str(regression),
            "--work-dir",
            str(work / "p4br"),
            "--output",
            str(output.with_name(evidence_name(output, "llvm-regression-"))),
        ],
        check=False,
    )
    return regression_run.returncode


if __name__ == "__main__":
    raise SystemExit(main())
