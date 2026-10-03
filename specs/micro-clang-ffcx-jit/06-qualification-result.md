# Phase 6 qualification result

**Decision:** COMPLETE — select **Option D: micro-Clang default candidate**.

This decision qualifies micro-Clang technically for a future default switch. It does **not** change the current default: LLVM-MinGW remains the normal/reference backend and the unconditional Windows `fenics-dolfinx` runtime dependency until a separate reviewed change updates package dependencies/default selection.

## Qualified implementation

- Pull request: #14 (`micro-clang/phase0-1`).
- base Phase-6 implementation head: `b632e35d3114c0787393cfdd04c637bde79897a6`.
- preferred Stage-6 ThinLTO payload source head: `cce65aafa0bf8a63bcd717eee25a01af910ea0a4`.
- Stage-6 downstream qualification head: `c4e0e4cb47d2cb983ca3eed313fa2ff8cac54b7b`.
- preferred Stage-7 Full-LTO source-build head: `5e6bd7fdf23b2c36fd3a6426039f5348035c7cb3`.
- Stage-7 focused measurement head: `52a3da9bfc999492d2cfb3fac6aaece446cbe638`.
- preferred Stage-7 downstream qualification head: `dbcc097f2a1084d89b92b280c96d98dc5a7f8a9d`.
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
| package-owned backend in paired comparison | 103.8560 MiB | reference backend |
| conda installed package contents | 103.98 MiB | 216.43 MiB |
| compressed conda package | 30.41 MiB | 51.34 MiB |
| standalone incremental micro-Clang payload | 108,908,574 bytes / 103.8633 MiB | not redefined here |

The mandatory early continuation gate (<=108.2 MiB) passes. The aspirational <=81.2 MiB strong-middle target and <=54.1 MiB stretch target are not reached.

The preferred Stage-7 standalone distribution is 307,924,966 bytes / 293.6601 MiB total. Common runtime + micro-Clang is 108,957,186 bytes / 103.9097 MiB; the micro-Clang incremental payload is 108,908,574 bytes / 103.8633 MiB.

## Generated-code and JIT performance

Stage-7 downstream run `37100978194` measured all three backends in the same runner/interpreter environment with alternating backend order.

micro-Clang versus freshly measured LLVM-MinGW:

| Python | assembly aggregate median | worst representative form | worst cold JIT | end-to-end Poisson |
| --- | ---: | ---: | ---: | ---: |
| 3.12 | 1.0007x | 1.0049x | 1.1396x | 1.0044x |
| 3.13 | 1.0017x | 1.0080x | 1.1189x | 1.0123x |
| 3.14 | 1.0002x | 1.0025x | 1.0786x | 1.0063x |

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

ThinLTO became the preferred qualified micro-Clang build profile at Stage 6.
It is retained as the historical LTO control; Stage 7 Full LTO subsequently
qualified a smaller payload without changing generated FFCx target-code policy.

## Post-qualification Stage 7 Full LTO

Stage 7 changed only the host compiler build from llvm-mingw `--thinlto` to
`--lto` / `LLVM_ENABLE_LTO=full`, while retaining the same pinned sources,
X86-only MinSizeRel/shared-`libLLVM` structure, strip policy, qualified target
sysroot/resource pruning and generated FFCx `-O2` policy.

Source build run `37093105472` passed. Focused measurement run
`37100266040` produced a **103.8251 MiB** complete backend, **2.3765 MiB /
2.2377%** smaller than the qualified ThinLTO parent. Full LTO increased the host
build time to about **67m20s**, so this reduction trades CI build cost for a
smaller shipped runtime.

Current-head downstream run `37100978194` passed Python 3.12-3.14
shared-runtime integration, paired three-backend performance and the
micro-Clang-only serial/MPI Nuitka standalone gate. The final conda package is
**103.98 MiB installed / 30.41 MiB compressed**, and the paired installed
backend is **103.8560 MiB**.

The standalone distribution is **307,924,966 bytes / 293.6601 MiB** total;
common runtime + micro-Clang is **108,957,186 bytes / 103.9097 MiB**, and the
micro-Clang incremental payload is **108,908,574 bytes / 103.8633 MiB**.
Serial fresh/cache JIT and representative forms passed, with four generated
modules, eight captured compiler/linker commands and Poisson solution norm
`0.4922541639224417`. The two-rank MPI ownership proof also passed.

Stage-7 evidence artifact `11266342583`
(`micro-clang-phase4-stage7-downstream`) has digest
`sha256:22a732813801ac6bd9753a7d1952e38420c1e18ba1d7f6ee016c2e487bcbe984`.

Full LTO is therefore the preferred qualified micro-Clang build profile. The
<=81.2 MiB aspirational target remains unmet.

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
