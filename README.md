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

Packages are published for **Windows 64-bit (`win-64`)** as stable-ABI (abi3,
`cp312`) builds — one binary serves **CPython 3.12, 3.13 and 3.14**. Python
3.11 and older are not supported (nanobind's stable ABI requires ≥ 3.12).

Prerequisites: any 64-bit Windows conda distribution (Miniforge, Miniconda,
Anaconda).

Install the whole stack (petsc, petsc4py, fenics-libdolfinx, fenics-dolfinx
plus Intel MPI, OpenBLAS, HDF5, basix/ffcx/ufl):

```bat
conda create -n fenics-windows python=3.12
conda activate fenics-windows
conda install -c precise-simulation -c conda-forge "libblas=*=*openblas" fenics-dolfinx
```

Any of `python=3.12`, `python=3.13` or `python=3.14` works; omitting the pin
lets the solver pick the newest supported interpreter.

Verify imports:

```bat
python -c "import dolfinx, petsc4py; print(dolfinx.__version__, petsc4py.__version__)"
```

A serial end-to-end check (no MPI launcher or firewall prompt):

```bat
python -c "from mpi4py import MPI; import dolfinx.mesh as m; m.create_unit_square(MPI.COMM_SELF, 8, 8); print('serial ok')"
```

Optional two-rank check:

```bat
mpiexec -localonly -n 2 python -c "from mpi4py import MPI; import dolfinx.mesh as m; m.create_unit_square(MPI.COMM_WORLD, 8, 8); print('rank', MPI.COMM_WORLD.rank, 'ok')"
```

Do not set `I_MPI_FABRICS=shm`: Intel MPI 2021.17 removed the plain `shm`
keyword (it warns "fabric ... has been removed ... use ofi or shm:ofi"), and
shared-memory transport between processes on one machine is selected
automatically anyway. If an older guide told you to set it, clear it with
`set I_MPI_FABRICS=`.

A FEniCS test script can be found in `scripts\test-poisson.py`, run:

```python
python test-poisson.py  # serial
mpiexec -n 2 python test-poisson.py  # 2 processes
```

### Silencing activation output

Activating an environment prints a page of Visual Studio toolchain probing
(`vs2022_compiler_vars.bat` echoes its SDK/compiler detection and the vcvars
banner). This is harmless but noisy. To suppress it:

```bat
powershell -ExecutionPolicy Bypass -File scripts\quiet-vs-activation.ps1 -Env fenics-windows
```

The script patches one package-owned file inside the environment, so rerun it
after any `conda update`, reinstall, or recreation of the environment. It is
idempotent and only affects console output during activation — compiler setup
is unchanged.

### Windows Firewall and MPI

Serial DOLFINx use does not start `mpiexec` and needs no firewall exception.

Multi-process runs use Intel MPI's Hydra launcher and can trigger a Windows
Firewall prompt for `mpiexec.exe` or a Hydra proxy. `-localonly` keeps process
launching on the local machine, but neither setting guarantees that the
launcher will avoid the firewall prompt.

A standard non-administrator user cannot create a permanent Windows Firewall
allow rule. If such a user receives the prompt, Windows can create block rules
regardless of the selected response. Users who do not need multi-process MPI
can use DOLFINx serially without administrator access or firewall prompts.

For multi-process MPI, an administrator or IT deployment can pre-create the
rules below. Run these commands from an elevated prompt. Rules are keyed to
the full executable path, so repeat them for each conda environment:

```bat
netsh advfirewall firewall add rule name="Intel MPI mpiexec"   dir=in action=allow program="%CONDA_PREFIX%\Library\bin\mpiexec.exe"          remoteip=127.0.0.1,localsubnet profile=any
netsh advfirewall firewall add rule name="Intel MPI hydra pmi" dir=in action=allow program="%CONDA_PREFIX%\Library\bin\hydra_pmi_proxy.exe"    remoteip=127.0.0.1,localsubnet profile=any
netsh advfirewall firewall add rule name="Intel MPI hydra bst" dir=in action=allow program="%CONDA_PREFIX%\Library\bin\hydra_bstrap_proxy.exe" remoteip=127.0.0.1,localsubnet profile=any
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
- **PT-SCOTCH integer width**: the win-64 conda-forge PT-Scotch **int64**
  build corrupts the process heap on any distributed-graph partition call
  (deferred `c0000374`/DOUBLE_FREE — crashes at teardown or later, ~always
  with repeated calls). The stack therefore pins `libscotch`/`libptscotch`
  to the **int32** builds, which are clean. Minimal repro:
  `python -c "from mpi4py import MPI; from dolfinx.cpp.graph import partitioner_scotch;
  from dolfinx.graph import adjacencylist; import numpy as np;
  g = adjacencylist(np.array([1,2,0,2,0,1], dtype=np.int64),
  np.array([0,2,4,6], dtype=np.int32))._cpp_object;
  partitioner_scotch()(MPI.COMM_SELF, 2, g, False)"` (crashes with int64
  builds even on one rank).
- Do **not** pass identical cell arrays on every MPI rank to
  `mesh.create_mesh` — that duplicates the global mesh and trips an
  unrelated redistribution edge case (heap corruption / wrong results).
  Provide cells on rank 0 (or distribute them) instead.
- Parallel `pc_type=lu` works via MUMPS, built from source and statically
  linked into libpetsc.dll (build 4+). conda-forge has no usable win-64
  mumps/scalapack packages, so petsc vendors both (flang toolchain).
  Serial LU unchanged; `ksp_type=cg, pc_type=gamg` also remains available.
  direct LU remains fine in serial.
- This channel is interim: packages retire as the corresponding
  conda-forge feedstock PRs land.

