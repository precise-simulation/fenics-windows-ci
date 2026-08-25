from mpi4py import MPI
from petsc4py import PETSc

import numpy as np
import ufl

import dolfinx
from dolfinx import fem, mesh
from dolfinx.fem.petsc import LinearProblem


def main():
    assert dolfinx.has_petsc
    assert dolfinx.has_petsc4py
    assert PETSc.Sys.getVersion() == (3, 25, 4)
    assert np.dtype(PETSc.ScalarType).kind == "f"
    assert np.dtype(PETSc.ScalarType).itemsize == 8
    assert np.dtype(PETSc.IntType).itemsize == 4

    domain = mesh.create_unit_square(MPI.COMM_WORLD, 8, 8)
    V = fem.functionspace(domain, ("Lagrange", 1))
    facets = mesh.locate_entities_boundary(
        domain,
        domain.topology.dim - 1,
        lambda x: np.isclose(x[0], 0)
        | np.isclose(x[0], 1)
        | np.isclose(x[1], 0)
        | np.isclose(x[1], 1),
    )
    dofs = fem.locate_dofs_topological(V, domain.topology.dim - 1, facets)
    boundary = fem.Function(V)
    boundary.interpolate(lambda x: x[0] + x[1])
    bc = fem.dirichletbc(boundary, dofs)

    u = ufl.TrialFunction(V)
    v = ufl.TestFunction(V)
    a = ufl.inner(ufl.grad(u), ufl.grad(v)) * ufl.dx
    # A plain `0 * v` collapses to ufl.Zero which carries no function spaces;
    # use a zero coefficient so the RHS form keeps its test space.
    zero = fem.Function(V)
    L = ufl.inner(zero, v) * ufl.dx
    print("STAGE 9 CG: build", flush=True)
    problem = LinearProblem(
        a,
        L,
        bcs=[bc],
        petsc_options_prefix="stage9_",
        petsc_options={
            "ksp_type": "cg",
            "pc_type": "jacobi",
            "ksp_rtol": 1e-12,
            "ksp_atol": 1e-14,
            "ksp_max_it": 100,
            "ksp_error_if_not_converged": True,
        },
    )
    print("STAGE 9 CG: solve", flush=True)
    solution = problem.solve()
    print("STAGE 9 CG: solved", flush=True)
    assert problem.solver.getConvergedReason() > 0

    expected = fem.Function(V)
    expected.interpolate(lambda x: x[0] + x[1])
    error = np.max(np.abs(solution.x.array - expected.x.array))
    assert domain.comm.allreduce(error, op=MPI.MAX) < 1e-10

    if domain.comm.rank == 0:
        print("STAGE 9 PETSC PASS")

    # direct solver path: static MUMPS linked into libpetsc.dll (win64);
    # exercises parallel LU factorization end to end
    print("STAGE 9 MUMPS: build", flush=True)
    problem_lu = LinearProblem(
        a,
        L,
        bcs=[bc],
        petsc_options_prefix="stage9_mumps_",
        petsc_options={
            "ksp_type": "preonly",
            "pc_type": "lu",
            "pc_factor_mat_solver_type": "mumps",
            "ksp_error_if_not_converged": True,
        },
    )
    print("STAGE 9 MUMPS: solve", flush=True)
    solution_lu = problem_lu.solve()
    print("STAGE 9 MUMPS: solved", flush=True)
    error_lu = np.max(np.abs(solution_lu.x.array - expected.x.array))
    assert domain.comm.allreduce(error_lu, op=MPI.MAX) < 1e-10

    if domain.comm.rank == 0:
        print("STAGE 9 MUMPS PASS")


if __name__ == "__main__":
    main()
