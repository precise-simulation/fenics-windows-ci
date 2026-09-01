#!/usr/bin/env python3
"""Resolve the conda-forge dependency stack that Windows CI should follow.

The solve is intentionally native linux-64: it asks conda-forge for the current
DOLFINx real-scalar stack and records the exact selected package versions/builds.
Windows CI consumes this JSON as dependency authority.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

# Keep this deliberately close to a user's Unix DOLFINx solve. DOLFINx itself
# must select petsc4py/SLEPc/SLEPc4py; constraining their build strings here can
# make libmamba backtrack to an obsolete DOLFINx generation even though a newer
# coherent stack exists.
REFERENCE_SPECS = [
    "python=3.12.*",
    "fenics-dolfinx",
    "mpich",
    "petsc=*=real_*",
]
REQUIRED = ("fenics-dolfinx", "petsc", "petsc4py", "slepc", "slepc4py", "hdf5", "mpich")


def run_solve(micromamba: str) -> dict:
    cmd = [
        micromamba,
        "create",
        "--dry-run",
        "--json",
        "--override-channels",
        "--strict-channel-priority",
        "-c",
        "conda-forge",
        "-n",
        "fenics-reference",
        *REFERENCE_SPECS,
    ]
    proc = subprocess.run(cmd, check=False, text=True, capture_output=True)
    if proc.returncode:
        sys.stderr.write(proc.stderr)
        raise RuntimeError(f"reference conda-forge solve failed with exit code {proc.returncode}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"micromamba did not return JSON: {proc.stdout[:1000]!r}") from exc


def package_map(solve: dict) -> dict[str, dict]:
    actions = solve.get("actions") or {}
    records = actions.get("LINK") or actions.get("link") or []
    by_name = {record.get("name"): record for record in records if record.get("name")}
    missing = [name for name in REQUIRED if name not in by_name]
    if missing:
        raise RuntimeError(f"reference solve is missing required packages: {', '.join(missing)}")
    return by_name


def compact_record(record: dict) -> dict:
    return {
        key: record.get(key)
        for key in ("name", "version", "build_string", "build_number", "channel", "subdir", "url")
        if record.get(key) is not None
    }


def major_minor(version: str) -> str:
    parts = version.split(".")
    if len(parts) < 2:
        raise RuntimeError(f"expected major.minor version, got {version!r}")
    return ".".join(parts[:2])


def build_reference(solve: dict) -> dict:
    records = package_map(solve)
    packages = {
        "fenics-dolfinx": compact_record(records["fenics-dolfinx"]),
        "petsc": compact_record(records["petsc"]),
        "petsc4py": compact_record(records["petsc4py"]),
        "slepc": compact_record(records["slepc"]),
        "slepc4py": compact_record(records["slepc4py"]),
        "hdf5": compact_record(records["hdf5"]),
        "mpi": compact_record(records["mpich"]),
    }

    petsc_family = major_minor(packages["petsc"]["version"])
    for name in ("petsc4py", "slepc", "slepc4py"):
        family = major_minor(packages[name]["version"])
        if family != petsc_family:
            raise RuntimeError(
                f"incoherent conda-forge PETSc family: petsc={petsc_family}, {name}={family}"
            )

    return {
        "schema": 1,
        "platform": "linux-64",
        "specs": REFERENCE_SPECS,
        "dolfinx_family": major_minor(packages["fenics-dolfinx"]["version"]),
        "petsc_family": petsc_family,
        "packages": packages,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--micromamba", default="micromamba")
    parser.add_argument("--output", default="reference-stack.json")
    args = parser.parse_args()

    reference = build_reference(run_solve(args.micromamba))
    output = pathlib.Path(args.output)
    output.write_text(json.dumps(reference, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(reference, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
