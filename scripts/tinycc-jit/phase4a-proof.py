"""Run Phase-4A/4B qualification plus the fresh TinyCC Phase-5 corpus."""

from __future__ import annotations

import os
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
        phase5_env = os.environ.copy()
        phase5_env["PYTHONHASHSEED"] = "0"
        phase5_diagnostics = output.parent / f"{output.stem}-phase5"
        phase5 = scripts / "phase5-functional-validation.py"
        phase5_run = subprocess.run(
            [
                sys.executable,
                str(phase5),
                "--cache-dir",
                str(work / "p5 integrated cache"),
                "--diagnostics-dir",
                str(phase5_diagnostics),
            ],
            check=False,
            env=phase5_env,
        )
        if phase5_run.returncode != 0:
            return phase5_run.returncode

        corpus_evidence = scripts / "phase5-corpus-evidence.py"
        corpus_run = subprocess.run(
            [
                sys.executable,
                str(corpus_evidence),
                "--diagnostics-dir",
                str(phase5_diagnostics),
            ],
            check=False,
            env=phase5_env,
        )
        if corpus_run.returncode != 0:
            return corpus_run.returncode

        phase5_stress = scripts / "phase5-stress-validation.py"
        stress_run = subprocess.run(
            [
                sys.executable,
                str(phase5_stress),
                "--work-dir",
                str(work / "p5 integrated stress"),
                "--output",
                str(output.parent / f"{output.stem}-phase5-stress.json"),
            ],
            check=False,
            env=phase5_env,
        )
        if stress_run.returncode != 0:
            return stress_run.returncode

        phase5_activation = scripts / "phase5-activation-validation.py"
        activation_run = subprocess.run(
            [
                sys.executable,
                str(phase5_activation),
                "--work-dir",
                str(work / "p5 activation validation"),
                "--output",
                str(output.parent / f"{output.stem}-phase5-activation.json"),
            ],
            check=False,
            env=phase5_env,
        )
        if activation_run.returncode != 0:
            return activation_run.returncode

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
            env=phase5_env,
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
