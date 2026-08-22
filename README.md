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

```
conda create -n fenics -c precise-simulation -c conda-forge "python=3.12|3.13|3.14" fenics-dolfinx
conda activate fenics
```

Pick any of the three Python versions; 3.12 is the safest default.

Verify:

```
python -c "import dolfinx, petsc4py; print(dolfinx.__version__, petsc4py.__version__)"
```

A quick end-to-end check (serial + two MPI ranks):

```
mpiexec -n 2 python -c "from mpi4py import MPI; import dolfinx.mesh as m; m.create_unit_square(MPI.COMM_WORLD, 8, 8); print('rank', MPI.COMM_WORLD.rank, 'ok')"
```

### Windows Firewall prompt

The first `mpiexec` run can trigger a Windows Firewall prompt for
`mpiexec.exe` / `hydra_pmi_proxy.exe`. **Click Allow** — while the prompt is
unanswered, Windows silently drops the launcher's connections and ranks die
at startup, which looks like a crashed job. Dismissing the prompt is worse:
Windows then writes a permanent *Block* rule and every later run fails until
that rule is deleted.

To pre-approve and never see the prompt (admin, once per env — rules are
keyed to the full exe path, so repeat per conda env):

```bat
netsh advfirewall firewall add rule name="Intel MPI mpiexec"   dir=in action=allow program="%CONDA_PREFIX%\Library\bin\mpiexec.exe"          remoteip=127.0.0.1,localsubnet profile=any
netsh advfirewall firewall add rule name="Intel MPI hydra pmi" dir=in action=allow program="%CONDA_PREFIX%\Library\bin\hydra_pmi_proxy.exe"    remoteip=127.0.0.1,localsubnet profile=any
netsh advfirewall firewall add rule name="Intel MPI hydra bst" dir=in action=allow program="%CONDA_PREFIX%\Library\bin\hydra_bstrap_proxy.exe" remoteip=127.0.0.1,localsubnet profile=any
```

Single-machine runs can additionally pin MPI to shared memory (no NIC access,
and the fastest transport locally; remove for real multi-node jobs):

```bat
set I_MPI_FABRICS=shm
```

Note this does **not** suppress the firewall prompt — that is triggered by
`mpiexec`'s launcher socket (bound to all interfaces), which `I_MPI_FABRICS`
does not control. Clicking **Allow** once per binary is the only way to stop
the prompts, and it needs no admin rights.

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
- Two-rank MPI runs can also exit non-zero *after* completing successfully
  (heap-corruption report at interpreter teardown). The work itself is fine —
  check rank output, not just the exit code. Affects all stack versions.
- This channel is interim: packages retire as the corresponding
  conda-forge feedstock PRs land.
