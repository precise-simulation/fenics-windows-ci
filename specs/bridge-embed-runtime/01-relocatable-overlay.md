# Relocatable embedded-runtime overlay for the MATLAB/Octave bridge

**Status:** done

## Goal

Produce one qualified Windows x64 CPython-3.12 FEniCS runtime overlay that can
be merged into the isolated runtime owned by precsim/python-matlab-octave-bridge.
The overlay must not require conda activation, an installed Visual Studio
toolchain, or the original conda prefix at runtime.

## Design decisions

- Overlay, not Python distribution: this repository continues to own the
  FEniCS/DOLFINx/PETSc/MPI/JIT closure while the bridge repository owns
  CPython embedding and its base runtime.
- CPython ABI: the first overlay targets Windows x64 CPython 3.12.
- NumPy: the bridge-facing overlay is qualified with NumPy 2.5.2 so the
  bridge's existing ndarray conversion contract remains stable.
- JIT: ship the production fenics-jit-runtime plus qualified Full-LTO
  fenics-jit-micro-clang 20260826; do not require Visual Studio or the Windows
  SDK at consumer runtime.
- Relocation: preserve conda-relative Lib/site-packages, Library/bin,
  Library/fenics-jit, runtime data, licenses, and CPython headers. A small
  bootstrap adds the relocated native DLL directory and rewrites PETSc/JIT
  roots relative to the embedded sys.prefix.
- Provenance: derive staged files from installed conda package ownership
  records, record package identities and file hashes, and reject conflicting
  ownership.
- Initial execution model: qualification is serial/in-process. Multi-rank
  MATLAB/Octave integration is not claimed by this overlay.

## Acceptance criteria

- [x] A normal published fenics-dolfinx environment with Python 3.12.10,
      NumPy 2.5.2 and OpenBLAS produces the overlay.
- [x] The payload contains the default micro-Clang backend and no LLVM-MinGW,
      TinyCC, VS2022 activation package, or ambient compiler dependency.
- [x] Every payload file is integrity-listed with package ownership/provenance.
- [x] The exact ZIP is merged into a clean non-conda CPython 3.12.10 runtime
      extracted to a path containing spaces.
- [x] Ambient Python and compiler/SDK variables are poisoned/removed during
      validation.
- [x] Relocated imports of NumPy, DOLFINx and petsc4py succeed and PETSc reports
      the relocated runtime/Library root.
- [x] A fresh FFCx Poisson JIT uses bundled micro-Clang, creates a generated
      .pyd, solves with PETSc, and prints the numerical result.
- [x] The original conda prefix is not required by the relocated runtime.

## Out of scope

- Linux/macOS bridge overlays.
- MATLAB/Octave process participation in a multi-rank MPI world.
- A PETSc sparse-value adapter in the bridge; that remains bridge-owned work.
- Publishing a permanent release asset before this overlay is qualified.
