# FEniCSx for Windows

Native 64-bit Windows conda packages for [FEniCSx](https://fenicsproject.org/), including DOLFINx, PETSc, petsc4py, HDF5, and MPI support.

These packages are built primarily for use with [FEATool Multiphysics](https://www.featool.com), providing its native Windows FEniCSx/PETSc backend, but they can also be installed and used directly from Python without WSL, Docker, or a Linux virtual machine.

Packages are published on the [precise-simulation](https://anaconda.org/precise-simulation) Anaconda channel.

## Installation

### Requirements

- Windows 10 or Windows 11, 64-bit
- Miniforge, Miniconda, or Anaconda
- CPython 3.12, 3.13, or 3.14

Create a dedicated conda environment and install DOLFINx:

```bat
conda create -n fenics-windows python=3.12
conda activate fenics-windows
conda install -c precise-simulation -c conda-forge "libblas=*=*openblas" fenics-dolfinx
```

Python 3.12, 3.13, and 3.14 are supported. The packages use Python's stable ABI, so the same DOLFINx binary can serve all supported interpreter versions.

The install pulls in the required Windows builds of PETSc, petsc4py, HDF5, Intel MPI, mpi4py, Basix, FFCx, UFL, PT-Scotch, MUMPS, OpenBLAS, and their dependencies.

## Verify the installation

Check that DOLFINx and PETSc can be imported:

```bat
python -c "import dolfinx, petsc4py; print('DOLFINx', dolfinx.__version__); print('petsc4py', petsc4py.__version__)"
```

Then create a small mesh:

```bat
python -c "from mpi4py import MPI; from dolfinx import mesh; mesh.create_unit_square(MPI.COMM_SELF, 8, 8); print('DOLFINx installation OK')"
```

If both commands complete successfully, the environment is ready for normal serial FEniCSx use.

## Running FEniCSx

A minimal example:

```python
from mpi4py import MPI
from dolfinx import mesh

domain = mesh.create_unit_square(MPI.COMM_WORLD, 16, 16)

print(
    f"Rank {MPI.COMM_WORLD.rank}: "
    f"{domain.topology.index_map(domain.topology.dim).size_local} cells"
)
```

Save this as `test.py` and run it serially:

```bat
python test.py
```

A more complete Poisson example is included in this repository as [`scripts/test-poisson.py`](scripts/test-poisson.py):

```bat
python scripts\test-poisson.py
```

## Parallel execution with MPI

The packages include Intel MPI and support multi-process DOLFINx runs.

Run the example above with two local MPI ranks:

```bat
mpiexec -localonly -n 2 python test.py
```

or run the bundled Poisson example:

```bat
mpiexec -localonly -n 2 python scripts\test-poisson.py
```

`-localonly` restricts process launching to the current computer.

### Windows Firewall

Serial DOLFINx use does not start `mpiexec` and normally requires no Windows Firewall changes.

Multi-process runs use Intel MPI's Hydra launcher and may trigger a Windows Firewall prompt for `mpiexec.exe` or one of the Hydra proxy executables. On managed systems, an administrator or IT deployment may need to allow these executables through the firewall.

Users who only need serial FEniCSx can use the packages without configuring MPI launcher firewall rules.

### Intel MPI fabric setting

Do not set:

```text
I_MPI_FABRICS=shm
```

Current Intel MPI versions select local shared-memory transport automatically. If an older configuration has this variable set, clear it with:

```bat
set I_MPI_FABRICS=
```

## Included functionality

The Windows stack includes:

- DOLFINx
- PETSc and petsc4py
- Intel MPI and mpi4py
- parallel HDF5 with local HDF5/XDMF support
- Basix
- FFCx
- UFL
- PT-Scotch mesh partitioning
- MUMPS sparse direct solver
- OpenBLAS

Parallel HDF5/XDMF files and distributed DOLFINx computations are supported.

PETSc's MUMPS direct solver is available, for example:

```python
ksp.setType("preonly")
pc = ksp.getPC()
pc.setType("lu")
pc.setFactorSolverType("mumps")
```

## Windows-specific notes

### PT-Scotch

The packages use the 32-bit-integer PT-Scotch build, which has been validated for DOLFINx mesh partitioning on Windows.

### Distributed mesh creation

When constructing distributed meshes manually, do not provide an identical complete copy of the global cell array independently on every MPI rank. Supply the mesh data on the root rank or distribute the input appropriately.

### OpenBLAS threads with MPI

For a strict rank-per-core MPI execution model, set:

```bat
set OPENBLAS_NUM_THREADS=1
```

This is optional for normal serial use.

## Updating

Update the environment with conda:

```bat
conda activate fenics-windows
conda update -c precise-simulation -c conda-forge fenics-dolfinx
```

## Package channel

Packages are published at:

[https://anaconda.org/precise-simulation](https://anaconda.org/precise-simulation)

This repository contains the recipes and CI infrastructure used to build and publish the native Windows packages.

## Reporting problems

For problems specific to these Windows packages, please open a GitHub issue and include:

- Windows version
- Python version
- output of `conda list`
- the command used to install the packages
- the complete error message

For general DOLFINx/FEniCSx usage questions that are not Windows-package specific, refer to the upstream [FEniCSx documentation](https://docs.fenicsproject.org/).
