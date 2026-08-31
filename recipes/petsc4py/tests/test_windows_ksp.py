import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys

import numpy as np
import petsc4py
from petsc4py import PETSc


def loaded_module_path(module_name):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleFileNameW.argtypes = [
        wintypes.HMODULE,
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    kernel32.GetModuleFileNameW.restype = wintypes.DWORD

    handle = kernel32.GetModuleHandleW(module_name)
    if not handle:
        return None
    path = ctypes.create_unicode_buffer(32768)
    length = kernel32.GetModuleFileNameW(handle, path, len(path))
    if not length:
        raise ctypes.WinError(ctypes.get_last_error())
    return path.value


def conda_records(package_name):
    conda_meta = Path(sys.prefix) / "conda-meta"
    records = []
    for record_path in sorted(conda_meta.glob(f"{package_name}-*.json")):
        with record_path.open(encoding="utf-8") as stream:
            record = json.load(stream)
        if record.get("name") == package_name:
            records.append((record_path, record))
    return records


def print_provenance():
    if PETSc.COMM_WORLD.getRank() != 0:
        return

    print("PETSC4PY_PROVENANCE_BEGIN")
    print(f"Python executable: {sys.executable}")
    print(f"Python prefix: {sys.prefix}")
    print(f"petsc4py module: {petsc4py.__file__}")
    print(f"PETSc extension: {PETSc.__file__}")

    for package_name in ("petsc", "petsc4py"):
        records = conda_records(package_name)
        if not records:
            print(f"Conda {package_name}: <no conda-meta record>")
            continue
        for record_path, record in records:
            print(
                f"Conda {package_name}: version={record.get('version')!r} "
                f"build={record.get('build')!r} channel={record.get('channel')!r}"
            )
            print(f"Conda {package_name} record: {record_path}")
            print(f"Conda {package_name} depends: {record.get('depends', [])!r}")

    for module_name in ("libpetsc.dll", "petsc.dll"):
        module_path = loaded_module_path(module_name)
        if module_path:
            print(f"Loaded {module_name}: {module_path}")

    print("PETSC4PY_PROVENANCE_END")


def check_interface():
    version = PETSc.Sys.getVersion()
    runtime_version = ".".join(str(part) for part in version)
    petsc_records = conda_records("petsc")
    assert len(petsc_records) == 1, [str(path) for path, _ in petsc_records]
    record_path, record = petsc_records[0]
    package_version = record.get("version")

    if PETSc.COMM_WORLD.getRank() == 0:
        print(f"PETSc runtime version: {version!r}")
        print(f"PETSc package version: {package_version!r} ({record_path})")

    assert runtime_version == package_version, (runtime_version, package_version)
    assert np.dtype(PETSc.ScalarType).kind == "f"
    assert np.dtype(PETSc.ScalarType).itemsize == 8
    assert np.dtype(PETSc.IntType).itemsize == 4


def solve():
    comm = PETSc.COMM_WORLD
    n = 16
    matrix = PETSc.Mat().createAIJ([n, n], nnz=3, comm=comm)
    matrix.setUp()
    start, end = matrix.getOwnershipRange()
    for row in range(start, end):
        columns = [row]
        values = [2.0]
        if row:
            columns.insert(0, row - 1)
            values.insert(0, -1.0)
        if row + 1 < n:
            columns.append(row + 1)
            values.append(-1.0)
        matrix.setValues(row, columns, values)
    matrix.assemblyBegin()
    matrix.assemblyEnd()
    matrix.setOption(PETSc.Mat.Option.SYMMETRIC, True)

    exact = matrix.createVecRight()
    exact.set(1.0)
    rhs = matrix.createVecLeft()
    matrix.mult(exact, rhs)
    solution = matrix.createVecRight()
    solution.set(0.0)

    ksp = PETSc.KSP().create(comm=comm)
    ksp.setOperators(matrix)
    ksp.setType(PETSc.KSP.Type.CG)
    ksp.getPC().setType(PETSc.PC.Type.JACOBI)
    ksp.setTolerances(rtol=1e-12, atol=1e-14, max_it=1000)
    ksp.solve(rhs, solution)

    reason = int(ksp.getConvergedReason())
    error = solution.copy()
    error.axpy(-1.0, exact)
    error_norm = error.norm()
    assert reason > 0, reason
    assert error_norm < 1e-10, error_norm

    if comm.getRank() == 0:
        print(f"KSP converged (reason {reason}), error norm {error_norm:.3e}")


if __name__ == "__main__":
    print_provenance()
    check_interface()
    solve()
    if PETSc.COMM_WORLD.getRank() == 0:
        print("STAGE 7 KSP PASS")
