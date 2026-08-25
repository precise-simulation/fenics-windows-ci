"""Poisson solve, MUMPS forced to METIS ordering (ICNTL(7)=5)."""
import sys
import time

t0 = time.time()
import numpy as np
import ufl
from dolfinx import fem, mesh
from dolfinx.fem.petsc import LinearProblem
from mpi4py import MPI

print(f"[{time.time()-t0:.1f}s] imports done rank {MPI.COMM_WORLD.rank}", flush=True)

domain = mesh.create_unit_square(MPI.COMM_WORLD, 24, 24)
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
zero = fem.Function(V)
L = ufl.inner(zero, v) * ufl.dx

expected = fem.Function(V)
expected.interpolate(lambda x: x[0] + x[1])

solvers = {
    "cg-gamg": {
        "ksp_type": "cg",
        "pc_type": "gamg",
        "ksp_rtol": 1e-12,
        "ksp_atol": 1e-14,
        "ksp_error_if_not_converged": True,
    },
    # ICNTL(7)=5 => METIS ordering: proves the metis-enabled MUMPS path end to end
    "lu-mumps-metis": {
        "ksp_type": "preonly",
        "pc_type": "lu",
        "pc_factor_mat_solver_type": "mumps",
        "mat_mumps_icntl_7": 5,
        "ksp_error_if_not_converged": True,
    },
}

failed = False
for name, opts in solvers.items():
    problem = LinearProblem(
        a,
        L,
        bcs=[bc],
        petsc_options_prefix=f"metistest_{name}_",
        petsc_options=dict(opts),
    )
    solution = problem.solve()
    err = np.max(np.abs(solution.x.array - expected.x.array))
    err = domain.comm.allreduce(err, op=MPI.MAX)
    ok = err < 1e-10
    failed |= not ok
    if domain.comm.rank == 0:
        print(f"PASS {name}: maxerr={err:.3e}" if ok
              else f"FAIL {name}: maxerr={err:.3e}", flush=True)

if domain.comm.rank == 0:
    print("ALL OK" if not failed else "SOME FAILED", flush=True)
sys.exit(1 if failed else 0)
