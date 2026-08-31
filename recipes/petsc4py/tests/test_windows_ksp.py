import numpy as np

from petsc4py import PETSc


def check_interface():
    version = PETSc.Sys.getVersion()
    if PETSc.COMM_WORLD.getRank() == 0:
        print(f"PETSc runtime version: {version!r}")
    assert version == (3, 25, 4), version
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
    check_interface()
    solve()
    if PETSc.COMM_WORLD.getRank() == 0:
        print("STAGE 7 KSP PASS")
