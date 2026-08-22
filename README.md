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

Install the whole stack:

```
conda create -n fenics -c precise-simulation -c conda-forge python=3.12 fenics-dolfinx
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
