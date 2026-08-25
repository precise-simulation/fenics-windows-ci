"""Taylor-Hood Stokes (P2-P1) on unit square, MUMPS LU direct.

Manufactured solution u=(x^2+y^2, -2xy), p=x+y (both exactly representable,
so residual error == solver precision). Pressure pinned at origin.

Usage: python test-stokes-mumps.py [n]   (default n=64, ~37k dofs)
Runs serially or under mpiexec; exit 0 iff every solver passes.
Run once serially before multi-rank (FFCx JIT cache warm-up).
"""
import sys

import basix
import numpy as np
import ufl
from dolfinx import fem, mesh
from dolfinx.fem.petsc import LinearProblem
from mpi4py import MPI


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 64
    comm = MPI.COMM_WORLD

    domain = mesh.create_unit_square(comm, n, n)
    tdim = domain.topology.dim
    domain.topology.create_connectivity(tdim - 1, tdim)

    cell = domain.basix_cell()
    W = fem.functionspace(domain, basix.ufl.mixed_element([
        basix.ufl.element("Lagrange", cell, 2, shape=(2,)),
        basix.ufl.element("Lagrange", cell, 1),
    ]))
    V, _ = W.sub(0).collapse()
    Q, _ = W.sub(1).collapse()
    ndofs = comm.allreduce(
        V.dofmap.index_map.size_local * V.dofmap.index_map_bs
        + Q.dofmap.index_map.size_local * Q.dofmap.index_map_bs, op=MPI.SUM)
    if comm.rank == 0:
        print(f"mesh {n}x{n}, {ndofs} dofs", flush=True)

    u_ex = fem.Function(V)
    u_ex.interpolate(lambda x: np.stack((x[0]**2 + x[1]**2, -2.0 * x[0] * x[1])))
    p_ex = fem.Function(Q)
    p_ex.interpolate(lambda x: x[0] + x[1])

    facets = mesh.exterior_facet_indices(domain.topology)
    dofs_u = fem.locate_dofs_topological((W.sub(0), V), tdim - 1, facets)
    bc_u = fem.dirichletbc(u_ex, dofs_u, W.sub(0))
    dofs_p = fem.locate_dofs_geometrical(
        (W.sub(1), Q), lambda x: np.isclose(x[0], 0) & np.isclose(x[1], 0))
    bc_p = fem.dirichletbc(fem.Function(Q), dofs_p, W.sub(1))

    u, p = ufl.TrialFunctions(W)
    v, q = ufl.TestFunctions(W)
    f = ufl.as_vector((-3.0, 1.0))
    a = (ufl.inner(ufl.grad(u), ufl.grad(v)) * ufl.dx
         - ufl.inner(p, ufl.div(v)) * ufl.dx
         + ufl.inner(q, ufl.div(u)) * ufl.dx)
    L = ufl.inner(f, v) * ufl.dx

    solvers = {
        "mumps-default-ordering": {
            "ksp_type": "preonly",
            "pc_type": "lu",
            "pc_factor_mat_solver_type": "mumps",
            "ksp_error_if_not_converged": True,
        },
        "mumps-metis": {
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
            a, L, bcs=[bc_u, bc_p],
            petsc_options_prefix=f"stokestest_{name}_",
            petsc_options=dict(opts),
        )
        wh = problem.solve()
        uh = wh.sub(0).collapse()
        ph = wh.sub(1).collapse()
        err_u = float(np.max(np.abs(uh.x.array - u_ex.x.array)))
        err_p = float(np.max(np.abs(ph.x.array - p_ex.x.array)))
        err = comm.allreduce(max(err_u, err_p), op=MPI.MAX)
        # ponytail: flat 1e-8; saddle-point pressure error grows ~h^-2 with
        # conditioning (6e-10 at n=64), tighten per-mesh only if needed
        ok = err < 1e-8
        failed |= not ok
        if comm.rank == 0:
            print(f"{'PASS' if ok else 'FAIL'} {name}: "
                  f"maxerr_u={err_u:.3e} maxerr_p={err_p:.3e}", flush=True)

    if comm.rank == 0:
        print("ALL OK" if not failed else "SOME FAILED", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
