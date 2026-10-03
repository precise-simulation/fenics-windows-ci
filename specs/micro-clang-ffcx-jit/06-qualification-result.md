# Phase 6 qualification result

**Decision:** COMPLETE — select **Option D: micro-Clang default candidate**.

This decision qualifies micro-Clang technically for a future default switch. It does **not** change the current default: LLVM-MinGW remains the normal/reference backend and the unconditional Windows `fenics-dolfinx` runtime dependency until a separate reviewed change updates package dependencies/default selection.

## Qualified implementation

- Pull request: #14 (`micro-clang/phase0-1`).
- base Phase-6 implementation head: `b632e35d3114c0787393cfdd04c637bde79897a6`.
- preferred Stage-6 ThinLTO payload source head: `cce65aafa0bf8a63bcd717eee25a01af910ea0a4`.
- Stage-6 downstream qualification head: `c4e0e4cb47d2cb983ca3eed313fa2ff8cac54b7b`.
- full Phase-6 workflow: `micro-clang-phase6` #8, run `37078092998`, successful.
- focused standalone confirmation: `micro-clang-phase6-standalone-retry` #3, run `37078092955`, successful.
- focused evidence artifact: `micro-clang-phase6-standalone-retry`, artifact `11257857090`.
- focused evidence SHA-256: `f577c7c15277f4a6cc9e61f6ccd902fbd2c611c47384b846db763d5b56cf64df`.
- pinned LLVM/Clang/LLD: LLVM 23.1.0 commit `ea7d852a70e8bdfaf601d6626a760f9771b2c4b4`.
- pinned mingw-w64: `a3d708261d5ba659205067cb82cae36e7ae8bbb0`.
- qualified backend cache identity in the standalone proof: `micro-clang-ea7d852a70e8-b3f0d58d50a3974f63d0`.

The initial controlled experiment uses the same LLVM/compiler-rt and mingw-w64 source identities as the immutable Stage-AW LLVM-MinGW reference, so the measured differences are attributable to toolchain construction/minimization rather than a compiler-version change.

## Size result

The qualified micro-Clang package is materially smaller than Stage-AW LLVM-MinGW:

| Measurement | micro-Clang | Stage-AW LLVM-MinGW |
| --- | ---: | ---: |
| package-owned backend in paired comparison | 106.2326 MiB | reference backend |
| conda installed package contents | 106.35 MiB | 216.43 MiB |
| compressed conda package | 30.67 MiB | 51.34 MiB |
| standalone incremental micro-Clang payload | 111,400,550 bytes / 106.2398 MiB | not redefined here |

The mandatory early continuation gate (<=108.2 MiB) passes. The aspirational <=81.2 MiB strong-middle target and <=54.1 MiB stretch target are not reached.

The preferred Stage-6 standalone distribution is 310,416,942 bytes total. Common runtime + micro-Clang is 111,449,162 bytes; the micro-Clang incremental payload is 111,400,550 bytes / 106.2398 MiB; staged development headers contribute 1,274,080 bytes.

## Generated-code and JIT performance

Dedicated paired same-run comparison run `36875583148` measured all three backends in the same runner/interpreter environment with alternating backend order.

micro-Clang versus freshly measured LLVM-MinGW:

| Python | assembly aggregate median | worst representative form | worst cold JIT | end-to-end Poisson |
| --- | ---: | ---: | ---: | ---: |
| 3.12 | 0.9975x | 1.0074x | 1.1602x | 0.9970x |
| 3.13 | 0.9942x | 1.0003x | 1.1534x | 1.0150x |
| 3.14 | 1.0054x | 1.0169x | 1.1096x | 1.0015x |

All supported versions satisfy the EPIC limits: assembly aggregate median <=1.10x, representative cases <=1.20x, cold JIT <=1.25x, numerical equivalence, and no material end-to-end PETSc regression.

Unlike TinyCC, micro-Clang therefore retains LLVM-class generated-code performance in the qualified corpus.

## Shared-runtime integration

The shared runtime now has explicit backend registration for:

- `llvm-mingw`;
- `tinycc`;
- `micro-clang`.

Qualification proved:

- LLVM-MinGW remains the selector default;
- an unavailable requested backend fails without silent fallback;
- backend package ownership does not overlap;
- each backend has a distinct physical cache namespace;
- sequential real-JIT switching across all three backends works;
- shared activation/concurrency semantics pass for micro/micro, LLVM/micro and TinyCC/micro contention;
- micro-Clang does not require either other compiler backend as a package dependency.

## Standalone result

The micro-Clang-only Nuitka proof passes with the original build prefix renamed and inaccessible and both LLVM-MinGW and TinyCC absent.

The serial proof confirms:

- minimal CFFI compile/import succeeds;
- fresh FFCx Poisson JIT succeeds;
- cache reuse succeeds;
- representative higher-order and facet forms compile;
- four FFCx cache modules are produced;
- eight micro-Clang compiler/linker commands are captured;
- bundle-local compiler, Python, UFCx and target inputs are used;
- the representative Poisson solution norm is `0.4922541639224417`;
- generated PE modules use Stable-ABI `python3.dll`, carry mitigation flags `0x160`, relocations and x64 unwind metadata.

The two-rank MPI proof confirms a shared fresh cache and rank-0 compile ownership. Rank 1's compiler path is deliberately replaced with a non-existent poison path; the JIT still completes, demonstrating that rank 1 does not launch an independent compiler.

## Post-qualification Stage 6 ThinLTO

A further host-build minimization was qualified after the original Phase-6
release decision.

`micro-clang-phase4-stage6-thinlto` #2 / run `37083171290` rebuilt the
same pinned X86-only MinSizeRel host compiler with upstream llvm-mingw
`--thinlto`, retained the existing strip policy, and reapplied the exact
qualified sysroot/resource reductions. The candidate measured **106.2016 MiB**
before conda packaging, a reduction of **1,765,586 bytes / 1.5607%** from its
Stage-5 parent measurement. The complete Python 3.12-3.14 private matrix passed.

`micro-clang-phase4-stage6-downstream` #1 / run `37090447506` then passed
the shared-runtime integration matrix, paired three-backend benchmark and
micro-Clang-only serial/MPI Nuitka standalone gate. The conda package is
**106.35 MiB installed / 30.67 MiB compressed**.

ThinLTO therefore becomes part of the preferred qualified micro-Clang build
profile. The reduction is modest and the <=81.2 MiB aspirational target remains
unmet, but there is no measured runtime-quality regression and no change to
generated FFCx target-code policy.

## Release decision

**Option D is selected: micro-Clang is a default candidate.**

The qualification rationale is:

- about half the installed footprint of Stage-AW LLVM-MinGW;
- LLVM-class generated-code performance;
- cold-JIT performance within the stated gate;
- broad Python 3.12-3.14 functional/numerical qualification;
- shared-selector/cache/concurrency/MPI qualification;
- hermetic micro-Clang-only standalone qualification;
- same-revision comparison against the immutable LLVM-MinGW reference.

This is **not a default switch**. The current Windows `fenics-dolfinx` package still installs `fenics-jit-llvm-mingw` unconditionally and the selector still defaults to `llvm-mingw`. Consequently this PR does not reduce the normal conda install footprint: side-by-side installation adds micro-Clang to the existing LLVM-MinGW dependency.

A future default switch must be a separate change that updates the normal package dependency/default selection and repeats the relevant integration, regression, performance and standalone gates. TinyCC remains the qualified compact backend.
