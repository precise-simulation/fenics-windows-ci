# micro-Clang execution status

**Status:** Phase 4 qualified. Stage 5 passed the <=108.2 MiB continuation gate at 107.8796 MiB and passed the complete Python 3.12-3.14 private matrix. Phase 5 shared-runtime three-backend integration is in progress; LLVM-MinGW remains the default.

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

## Phase 0-1 qualification evidence

Workflow run #30 (`36232509736`) at head
`6c0f3fc562eb9291f9ca58eb6e64cc454b273056` cleared the ordered Phase 0-1
gate:

- Phase 0 Stage-AW reference: passed;
- Phase 1 source build: passed;
- Phase 1 private proof Python 3.12: passed;
- Phase 1 private proof Python 3.13: passed;
- Phase 1 private proof Python 3.14: passed;
- Python 3.15 remains informational and failed during environment installation,
  before the private proof, so it is not a blocking supported-version result.

The source-built payload reported 3,382 files / 375,006,631 bytes
(357.6342 MiB). This is a Phase-1 feasibility staging size, not the Phase-4
continuation measurement and not a claim that the early <=108.2 MiB size gate
has passed.

The blocking private proofs established fresh minimal CFFI and Poisson JIT,
Stage-AW ABI and target-default equivalence, Stable-ABI Python linking, PE
hardening/relocations/x64 unwind metadata, hostile ambient-tool isolation, and
paths containing spaces.

## Phase 2: conservative package

Phase 2 now relocates the complete source-built payload under
`Library/fenics-jit/backends/micro-clang`, adds the qualified private runtime
helper, Stable-ABI import libraries for Python 3.12-3.14, source/build
provenance, retained-file manifest, complete payload measurement, and LLVM /
llvm-mingw / mingw-w64 license notices. The package is verified after relocation
with a fresh DLL compile in a path containing spaces.

This phase deliberately does **not** add `micro-clang` to the production
shared selector and does not change the LLVM-MinGW default. It also does not
apply the Phase-4 size gate: the conservative package is the baseline from
which measured minimization must proceed.


## Phase 2 qualification evidence

Workflow run #35 (\`36292484662\`) at head
\`2947adb45176b03d89821a73b63fa2a0a093d0e5\` cleared the conservative
package/reproducibility gate:

- the finalized backend payload was measured after generated package metadata,
  manifest and size files were written: 3,404 files / 359.373 MiB;
- a second package reconstructed from the same immutable Phase-1 inputs under an
  independent clean work root reported the same finalized file count and size;
- \`metadata.json\`, \`manifest.csv\`, and \`size.txt\` matched by SHA-256
  between the two clean package roots;
- the retained source/build provenance and LLVM / llvm-mingw / mingw-w64
  license material were present in the installed layout;
- both the primary package and reconstructed package passed relocation smoke
  from paths containing spaces;
- the production selector remained untouched and LLVM-MinGW remained the
  default/reference backend.

The conservative 359.373 MiB footprint is intentionally not a Phase-4 size
success. It is the complete pre-minimization baseline from which reversible,
measured reductions must start.

## Phase 3: private broad qualification

Phase 3 is now implemented as a private Python 3.12-3.14 blocking matrix with
Python 3.15 informational. It installs the qualified Phase-2 package into an
isolated prefix containing spaces without registering a production selector
entry.

Each supported job:

1. re-runs the Phase-1 ABI/driver/PE/hermeticity contract against the installed
   Phase-2 package and immutable Stage-AW reference;
2. reuses the established LLVM-MinGW broad FFCx form validator for scalar
   Poisson, vector elasticity, coefficient/facet forms, nonlinear
   residual/Jacobian, \`fem.Expression\`, cache reuse, Stable-ABI imports and
   PE inspection;
3. hash-checks the generated C for the established eight-module repository
   corpus contract on Python 3.12-3.14;
4. adds higher-order P3, explicit interior-facet \`dS\`, exterior-facet \`ds\`
   and coefficient-heavy P3 coverage;
5. compares those numerical results directly with the installed LLVM-MinGW
   reference in the same interpreter/job;
6. proves a cache reload from a new Python process performs no compiler/linker
   work;
7. runs two simultaneous private micro-Clang JIT processes to exercise
   concurrent compiler/package use while shared-selector thread serialization
   remains deliberately deferred to Phase 5;
8. runs the established two-rank MPI JIT/cache proof and requires rank-0 compile
   ownership with rank 1 loading the shared cache;
9. keeps hostile Visual Studio/Windows SDK/compiler configuration poisoning and
   package-root command checks active throughout micro-Clang compilation.

No \`FENICS_JIT_COMPILER=micro-clang\` selector path is added in Phase 3.

## Phase 3 qualification evidence

Workflow run #40 (`36373061120`) at head
`277e36652301f41c8bbd607bc7c34d7a96f6b0f8` cleared the private broad
qualification gate:

- Phase 3 Python 3.12: passed;
- Phase 3 Python 3.13: passed;
- Phase 3 Python 3.14: passed;
- Python 3.15 remains informational and failed during environment installation,
  before private qualification, so it is not a blocking supported-version
  result.

The blocking jobs re-ran the Phase-1 ABI/driver/PE/hermeticity contract and
passed the broad generated-C corpus, additional P3/facet/coefficient coverage,
new-process cache reload, direct LLVM-MinGW numerical comparison, concurrent
private processes, and two-rank MPI rank-0 compile/rank-1 cache-load proof.
The installed production selector was not used or modified.

## Phase 4 stage 1 qualification evidence

Workflow run #45 (`36384660189`) at head
`11e00075ef81e13509a2dd0b3a1c887911f23726` qualified the first
reversible minimization stage:

- the complete Stage-1 backend measured 259,191,062 bytes / 247.1839 MiB;
- this removed 117,638,845 bytes (31.218%) from the 376,829,907-byte
  conservative Phase-2 baseline;
- clean-root package reconstruction reproduced `metadata.json`,
  `manifest.csv`, and `size.txt` byte-for-byte by SHA-256;
- package relocation smoke passed;
- the complete private qualification passed on Python 3.12, 3.13 and 3.14,
  including ABI/driver/PE/hermeticity, broad generated-C corpus, numerical
  comparison, cache reload, concurrency and two-rank MPI ownership.

The Stage-1 reduction uses a MinSizeRel host compiler, keeps the shared LLVM
core, links Clang without the monolithic `libclang-cpp` DLL, and removes
host development/tooling artifacts. The conservative target sysroot was left
unchanged.

The early Phase-4 continuation gate is **not** satisfied:
247.1839 MiB > 108.2 MiB. Phase 5 must therefore remain blocked while further
measured Phase-4 minimization proceeds.

## Phase 4 stage 2 qualification evidence

Workflow run #51 (`36425414167`) at head
`62a8ecce67ea38ed0f6c88d59c47b5b3bdffa4d6` qualified the second
reversible minimization stage:

- the complete Stage-2 backend measured **163.0088 MiB**;
- Stage 2 reused the same-revision immutable Stage-AW measured-unobserved
  Windows API header/import-library families and removed remaining IDL/TLB
  metadata;
- clean-root reconstruction and relocation/package smoke passed;
- the complete private qualification passed on Python 3.12, 3.13 and 3.14;
- closure tracing was enabled across the blocking matrix to provide the input
  for the next measured sysroot reduction.

Stage 2 is about 54.6% smaller than the 359.373 MiB conservative Phase-2
baseline, but it remains **54.8088 MiB above** the early continuation gate.
Phase 5 therefore remains blocked.

Stage 3 uses those qualified Stage-2 dependency/link-map traces to remove only
unobserved non-core headers and optional target import archives while retaining
explicit C/UCRT/POSIX and startup/runtime/default-Windows safety sets. The
candidate must again reproduce cleanly and pass the complete Python 3.12-3.14
private matrix before it can be accepted.

## Phase 4 stage 3 qualification evidence

Workflow run #56 (`36488264568`) at head
`5efa0fad112f06374d0eacef2d332b64d2a6dd3c` revalidated the unchanged
Stage-3 tree after the failed/reverted host-strip edit and cleared the complete
Stage-3 gate:

- complete backend: **112.938 MiB**;
- the closure-driven reduction removed **49.8661 MiB**, comprising 1,283
  trace-unobserved non-core headers and 802 optional import archives;
- the candidate was derived from 48 compiler dependency traces and 48 LLD map
  traces while retaining the explicit C/UCRT/POSIX and
  startup/runtime/default-Windows safety sets;
- independent package reconstruction reproduced metadata, manifest and size;
- relocation/package smoke passed;
- complete private qualification passed on Python 3.12, 3.13 and 3.14.

Stage 3 remains **4.738 MiB above** the 108.2 MiB continuation gate, so Phase 5
remains blocked.

Stage 4 is a separate reversible host-only reduction. It uses the source-built
`llvm-strip --strip-all` on the retained Clang/LLD/LLVM/libc++/libunwind PE
closure, records per-file bytes removed, then reapplies the already-qualified
Stage-AW and Stage-3 sysroot reductions. It must reproduce cleanly and pass the
complete Python 3.12-3.14 private matrix before acceptance. Target-code
generation policy, target sysroot safety policy, selector and default remain
unchanged.

## Phase 4 stage 4 qualification evidence

Workflow run #58 (`36535571413`) at head
`70f9be39ee7729c234a3955f642a2fd4a30a2dd5` qualified Stage 4:

- complete backend: **112.1238 MiB**;
- source-built `llvm-strip --strip-all` removed **0.8169 MiB** from the
  retained host PE closure;
- the qualified Stage-AW and Stage-3 sysroot reductions were reapplied
  unchanged;
- independent package reconstruction reproduced metadata, manifest and size;
- relocation/package smoke passed;
- complete private qualification passed on Python 3.12, 3.13 and 3.14.

Stage 4 remains **3.9238 MiB above** the 108.2 MiB continuation gate, so Phase
5 remains blocked.

The remaining package includes about 7.44 MiB of Clang resource headers.
Pinned LLVM 23.1 `clang/lib/Headers/CMakeLists.txt` explicitly separates
core, x86, Windows and utility resource headers from ARM/AArch64, CUDA,
Hexagon, HIP, HLSL, LoongArch, MIPS, OpenCL, PowerPC, RISC-V, SPIR-V,
SystemZ/zOS, VE, WebAssembly, generic GPU, OpenMP-device, LLVM-offload and
LLVM-libc-wrapper groups. Stage 5 removes only those non-x86/GPU-offload
groups (about 4.25 MiB) while retaining the complete core/x86/Windows/utility
resource sets and the qualified target C/UCRT sysroot. Full private
qualification remains mandatory.

## Phase 4 stage 5 qualification evidence

Workflow run #61 (`36582260173`) at head
`7dca0126c3cc55e7a1131a44e3b7607c536c2516` cleared the complete Phase-4
continuation gate:

- the complete Stage-5 backend measured **107.8796 MiB**;
- Stage 5 removed **4.2531 MiB / 111 files** from pinned LLVM non-x86 and
  GPU/offload Clang resource-header groups while retaining core, x86, Windows
  and utility resource headers;
- clean reconstruction reproduced package metadata, manifest and size;
- relocation/package smoke passed;
- the complete blocking private qualification passed on Python 3.12, 3.13 and
  3.14;
- the final backend is below the **108.2 MiB** early continuation gate.

Phase 4 is therefore qualified and Phase 5 shared-runtime integration may
proceed. LLVM-MinGW remains the default. No normal-install footprint reduction
is claimed because the current Windows `fenics-dolfinx` package still depends
on `fenics-jit-llvm-mingw` unconditionally.

## Phase 5 integration work

The first Phase-5 integration slice adds an explicit three-backend selector
registration for `llvm-mingw`, `tinycc`, and `micro-clang`, a backend-owned
micro-Clang runtime/cache identity, and a separately owned
`fenics-jit-micro-clang` package candidate produced from the qualified
Stage-5 payload. CI must prove on Python 3.12-3.14 that all three selectors load
the intended backend, unavailable backends fail without fallback, package
ownership/dependencies do not overlap, backend cache namespaces are distinct,
sequential switching performs real JIT, and micro-Clang participates safely in
the shared activation/concurrency contract.

## Gates before further implementation

Phase 2 packaging may proceed because Phase 0 and the required Phase 1 matrix
passed in workflow run #30.

Phase 3 broad qualification may proceed because workflow run #35 passed the
conservative Phase-2 package/relocation/provenance/reproducibility gate.

Phase 4 minimization may now proceed because the blocking Python 3.12-3.14
Phase-3 private qualification matrix passed in workflow run #40.

Do not start production shared-runtime integration until the Phase-3 private
qualification and Phase-4 size/performance gates pass. LLVM-MinGW remains the
default/reference backend throughout these phases.
