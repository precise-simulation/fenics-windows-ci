"""test-poisson.py - FEniCS solver test script.

Poisson on the unit circle: -laplace(u) = 4, u = 0 on boundary.
Exact solution u = 1 - x^2 - y^2."""

import basix.ufl
import numpy as np
import ufl
from dolfinx import fem, mesh
from dolfinx.fem.petsc import LinearProblem
from mpi4py import MPI

# structured disk mesh (rings of triangles), no gmsh needed
nr, nt = 16, 32
t = np.linspace(0.0, 2.0 * np.pi, nt, endpoint=False)
points = [(0.0, 0.0)] + [(r * np.cos(a), r * np.sin(a)) for r in np.linspace(0, 1, nr + 1)[1:] for a in t]
cells = [(0, 1 + i, 1 + (i + 1) % nt) for i in range(nt)]
for k in range(nr - 1):
    a0, b0 = 1 + k * nt, 1 + (k + 1) * nt
    for i in range(nt):
        a1, a2, b1, b2 = a0 + i, a0 + (i + 1) % nt, b0 + i, b0 + (i + 1) % nt
        cells += [(a1, a2, b2), (a1, b2, b1)]

# ponytail: multi-rank runs of this stack crash nondeterministically in mesh
# partitioning (heap corruption); run serial until precise-simulation fixes it
# ponytail: pass cells on rank 0 only - identical input on every rank would
# duplicate the global mesh (and trips a dolfinx redistribution edge case)
cells = np.array(cells, dtype=np.int64) if MPI.COMM_WORLD.rank == 0 else np.empty((0, 3), dtype=np.int64)
domain = mesh.create_mesh(
    MPI.COMM_WORLD,
    cells,
    ufl.Mesh(basix.ufl.element("Lagrange", "triangle", 1, shape=(2,))),
    np.array(points),
)

V = fem.functionspace(domain, ("Lagrange", 1))
domain.topology.create_connectivity(domain.topology.dim - 1, domain.topology.dim)
bc = fem.dirichletbc(0.0, fem.locate_dofs_topological(
    V, domain.topology.dim - 1, mesh.exterior_facet_indices(domain.topology)), V)

u, v = ufl.TrialFunction(V), ufl.TestFunction(V)
# ponytail: direct LU has no parallel factorizer in this stack (no MUMPS);
# use iterative GAMG on >1 rank
ksp = {"ksp_type": "preonly", "pc_type": "lu"} if MPI.COMM_WORLD.size == 1 \
    else {"ksp_type": "cg", "pc_type": "gamg", "ksp_rtol": 1e-10}
problem = LinearProblem(ufl.dot(ufl.grad(u), ufl.grad(v)) * ufl.dx,
                        fem.Constant(domain, 4.0) * v * ufl.dx, bcs=[bc],
                        petsc_options=ksp,
                        petsc_options_prefix="poisson_disk")
uh = problem.solve()

u_exact = fem.Function(V)
u_exact.interpolate(lambda x: 1.0 - x[0]**2 - x[1]**2)
err = np.sqrt(domain.comm.allreduce(
    fem.assemble_scalar(fem.form((uh - u_exact)**2 * ufl.dx)), op=MPI.SUM))
if domain.comm.rank == 0:
    print("L2 error:", err)
