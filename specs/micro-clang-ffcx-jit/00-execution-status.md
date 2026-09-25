# micro-Clang execution status

**Status:** Phase 0-1 implementation; production integration remains gated on CI evidence.

This file records execution of `EPIC.md`. The epic is intentionally sequential:
later phases must not be implemented merely because their code could be written
before the earlier qualification gates have passed.

## Phase 0: immutable reference

The source identity used by the Stage-AW control is now pinned in
`scripts/micro-clang-jit/reference-identity.json`:

- llvm-mingw release `20260826`, tag object
  `993b5219b769cc59cb9b48be56e5edfd9e5c6226`, commit
  `14614551fb5fc0f725933e4959c75c06d347acfa`;
- LLVM/Clang/LLD and compiler-rt `llvmorg-23.1.0`, tag object
  `9b0f9b1eb4a233717c6ed014cff6f8a7c65512de`, commit
  `ea7d852a70e8bdfaf601d6626a760f9771b2c4b4`;
- mingw-w64 commit
  `a3d708261d5ba659205067cb82cae36e7ae8bbb0`;
- immutable reference archive
  `llvm-mingw-20260826-ucrt-x86_64.zip`, SHA-256
  `ae601f4e0f72bbdf441ad2df8bb16f037e2e9251559ea6b37b4057aef39c06c3`.

The Phase-0 workflow reconstructs the **immutable** Stage-AW staged payload
from the exact qualification head `1d970c7372c673b086ce75210b865768b2b18e42`
(PR #9, qualification run `34580520920`), not from the moving `main` recipe.
It replays Stage I through Stage AW after base staging, requires the staged
payload to remain within 0.25 MiB of the recorded 215.19 MiB control, captures
the target/driver defaults and ABI sentinel, and writes a machine-readable
installed/compressed category decomposition.

## Phase 1: source-build feasibility

The private Phase-1 path:

1. uses the immutable Stage-AW archive only as a build bootstrap;
2. builds Clang/LLD from the exact pinned LLVM commit with only the X86 backend;
3. builds mingw-w64/UCRT, compiler-rt builtins and static libunwind from the
   exact pinned source identities;
4. reproduces the llvm-mingw target-wrapper policy for compiler-rt,
   libunwind and LLD;
5. removes unneeded C++ target payload and non-required host executables;
6. records the CMake cache, build-tool versions, source revisions, retained
   manifest and payload size;
7. runs the existing qualified LLVM-MinGW CFFI runtime helper through a private
   micro-Clang root rather than adding a production selector entry;
8. disables the installed production LLVM-MinGW backend during the proof;
9. qualifies Python 3.12, 3.13 and 3.14, with Python 3.15 informational;
10. requires the Stage-AW ABI sentinel and CPU/feature defaults to match;
11. requires Stable-ABI `python3.dll` linking, PE mitigation bits,
    relocations and x64 `.pdata` unwind metadata;
12. poisons Visual Studio/Windows SDK/compiler environment inputs and rejects
    any command-log reference to those inputs or the normal LLVM-MinGW backend;
13. exercises work, cache and toolchain paths containing spaces.

The DOLFINx production selector remains unchanged. The private Poisson proof
temporarily bypasses the selector hook while the already-active private
micro-Clang runtime is in scope. This is deliberate: adding
`FENICS_JIT_COMPILER=micro-clang` is a Phase-5 action and may occur only after
the private qualification and size gates pass.

## Gates before further implementation

Do not start Phase 2 packaging until Phase 0 and Phase 1 pass in
`.github/workflows/micro-clang-jit.yml`.

Do not start production shared-runtime integration until the Phase-3 private
qualification and Phase-4 size/performance gates pass. LLVM-MinGW remains the
default/reference backend throughout these phases.
