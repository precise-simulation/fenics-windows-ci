# fenics-windows-ci

Automated win-64 builds of the PETSc → petsc4py → DOLFINx stack, published to
the [precise-simulation](https://anaconda.org/precise-simulation) anaconda
channel.

## What it does

A scheduled daily workflow (plus a manual button) checks upstream releases
against what is already published. When anything changed it rebuilds the
affected stages **in dependency order** — petsc, then petsc4py, then dolfinx,
each consuming the previous stage's fresh output — and uploads new `.conda`
files to the channel.

## Installation

Packages are published for **Windows 64-bit (`win-64`)** and built against
**CPython 3.12** — `petsc4py` pins `python 3.12.*`, so the solver resolves
only with Python 3.12. Other Python versions (3.10, 3.11, 3.13+) are not
available from this channel.

Prerequisites: any 64-bit Windows conda distribution (Miniforge, Miniconda,
Anaconda).

Install the whole stack (petsc, petsc4py, fenics-libdolfinx, fenics-dolfinx
plus Intel MPI, OpenBLAS, HDF5, basix/ffcx/ufl):

```
conda create -n fenics -c precise-simulation -c conda-forge python=3.12 fenics-dolfinx
conda activate fenics
```

Keep `python=3.12` exactly as shown — it is the only supported version, not
an example.

Verify:

```
python -c "import dolfinx, petsc4py; print(dolfinx.__version__, petsc4py.__version__)"
```

A quick end-to-end check (serial + two MPI ranks):

```
mpiexec -n 2 python -c "from mpi4py import MPI; import dolfinx.mesh as m; m.create_unit_square(MPI.COMM_WORLD, 8, 8); print('rank', MPI.COMM_WORLD.rank, 'ok')"
```

## Manual trigger

Actions → *stack* → **Run workflow**

- `force_all` — rebuild everything even if versions are unchanged (use after
  conda-forge dependency drift such as an Intel MPI / OpenBLAS / HDF5 update)
- `upload` — publish results (default on; turn off for test runs)

## Notes

- Runs on `windows-latest` (VS2022 preinstalled); recipes are self-contained:
  MSVC is driven through PETSc's `win32fe`, bash/make come from `m2-*`
  packages, no system Cygwin involved.
- First-ever two-rank MPI run on a machine can hit an FFCx JIT cache race;
  run one serial solve first if you see a crash in rank 1.
- This channel is interim: packages retire as the corresponding
  conda-forge feedstock PRs land.
