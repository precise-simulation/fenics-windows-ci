# EPIC: micro-Clang runtime compiler for FFCx JIT on Windows

## Status

**Status:** proposed — plan only.

This proposal evaluates a purpose-built minimal Clang/LLD toolchain as a third Windows FFCx/CFFI JIT backend between the qualified TinyCC and LLVM-MinGW options.

No runtime default, package dependency, backend selector, or production behavior changes as part of this proposal. LLVM-MinGW remains the normal/reference backend until a later qualification explicitly decides otherwise.

## Motivation

The currently qualified backends expose a useful but wide tradeoff:

- TinyCC is extremely small (about 2.2 MiB installed) and has very fast cold JIT, but representative generated assembly can be materially slower than LLVM-MinGW, including about 4.4x for the higher-order P3 family.
- LLVM-MinGW provides the reference generated-code performance and conservative compatibility envelope, but the immutable Stage-AW package is about 216.43 MiB installed / 51.34 MiB compressed.

The purpose of micro-Clang is to test whether most of LLVM-MinGW's generated-code quality can be retained with a substantially smaller dedicated compiler payload.

The experiment is specifically about **building a smaller compiler**, not only pruning another general-purpose binary distribution after the fact.

## Goal

Provide a package provisionally named:

~~~text
fenics-jit-micro-clang
~~~

containing only the Clang/LLD and Windows target pieces required for FFCx/CFFI runtime JIT:

- x86-64 Clang C frontend/driver;
- LLD PE/COFF linker support;
- X86 LLVM code generator only;
- the minimal Clang resource headers/runtime required by generated C;
- the required mingw-w64/UCRT C headers and target startup/import libraries;
- compiler-rt builtins or other target runtime pieces proven necessary;
- backend metadata and diagnostics support.

The package is not a general-purpose LLVM development environment.

## Definition of micro-Clang

"micro-Clang" means a source-built, feature-minimized Clang/LLD toolchain configured specifically for the FEniCS Windows runtime JIT contract.

The preferred construction is an exact pinned LLVM source revision plus exact pinned mingw-w64/runtime sources, built with a minimal configuration such as:

- LLVM target: X86 only;
- LLVM projects: Clang and LLD only;
- no LLDB;
- no MLIR;
- no clang-tools-extra;
- no Polly;
- no OpenMP unless qualification proves it is required;
- no sanitizers, profilers, fuzzers, ORC JIT, or unsupported target runtimes;
- tests/examples/benchmarks/docs disabled in the shipped build;
- static or otherwise self-contained host compiler linkage where practical;
- only the PE/COFF linker path needed by the Clang driver;
- no C++ target standard library in the runtime payload;
- only the x86-64 Windows target sysroot.

The exact CMake/build configuration must be captured in package metadata and treated as part of backend identity.

## Build strategy

The implementation should test the following in order:

1. **Source-built Clang/LLD host tools.**
   Build only the LLVM components needed to produce the Clang driver/frontend and LLD PE/COFF linker.

2. **Minimize host-tool dependencies at build time.**
   Prefer a compiler configuration that does not require a large set of shared LLVM/Clang DLLs in the runtime package. Static host CRT linkage may be considered if licensing, reproducibility, and Windows compatibility remain acceptable.

3. **Construct an x86-64 Windows target sysroot.**
   Build/stage only the mingw-w64/UCRT headers, startup objects, import libraries, and target runtime archives needed for C shared-library output.

4. **Preserve the qualified ABI model.**
   Generated modules must remain compatible with MSVC-built CPython/DOLFINx and continue to use the established Stable-ABI python3.dll link strategy.

5. **Minimize only from measured evidence.**
   Any reduction of headers/import libraries must be backed by the existing broad FFCx corpus plus explicit sentinel tests. Do not infer safety solely from the Poisson example.

Using llvm-mingw build machinery as a reproducible source-build bootstrap is acceptable if the resulting package is genuinely purpose-built/minimized rather than merely repackaging the normal upstream binary archive.

## Runtime ownership and integration

The already-merged shared runtime architecture remains authoritative:

~~~text
fenics-jit-runtime
  Library/fenics-jit/runtime/...

fenics-jit-llvm-mingw
  Library/fenics-jit/backends/llvm-mingw/...

fenics-jit-tinycc
  Library/fenics-jit/backends/tinycc/...

fenics-jit-micro-clang
  Library/fenics-jit/backends/micro-clang/...
~~~

The experiment must not duplicate or replace shared selector/lifecycle ownership.

Until private qualification passes, micro-Clang should use a private activation/proof path and must not change the production backend selector.

Only after the private gate may the shared selector gain:

~~~text
FENICS_JIT_COMPILER=micro-clang
~~~

LLVM-MinGW remains the default throughout qualification.

No silent fallback between backends is allowed.

## CFFI/setuptools integration

Because micro-Clang intentionally preserves the GNU/MinGW Clang driver model, the first implementation should reuse the already-qualified LLVM-MinGW CFFI/setuptools contract as closely as possible.

The preferred path is:

~~~text
UFL
  -> FFCx generated C
  -> CFFI / setuptools
  -> owned Windows JIT activation
  -> micro-Clang driver
  -> LLD PE/COFF
  -> .pyd
  -> DOLFINx
~~~

Do not introduce a custom CFFI compiler adapter unless the source-built toolchain cannot satisfy the existing qualified MinGW-style build path.

Any divergence from the LLVM-MinGW compiler/link flags must be explicit and benchmarked because generated-code equivalence is a primary objective.

## Cache identity

micro-Clang must have a distinct immutable physical cache namespace selected before FFCx performs cache lookup:

~~~text
<cache>/ffcx/micro-clang/<backend-cache-id>/...
~~~

The backend cache identity must change when any binary-compatibility input changes, including:

- LLVM/Clang/LLD source revision;
- local LLVM patches;
- mingw-w64/runtime revision;
- target sysroot manifest;
- host compiler build configuration;
- optimization/code-generation flags;
- Python Stable-ABI import-library policy;
- CRT model;
- PE hardening configuration;
- backend/runtime adapter schema.

No cache artifact may be shared with llvm-mingw or tinycc.

## Reference baselines

Use immutable qualified results rather than moving package state.

### LLVM-MinGW reference

Use Stage AW merged through PR #9:

- qualification run: stack #231 (34580520920);
- staged payload: 215.19 MiB;
- installed package: 216.43 MiB;
- compressed package: 51.34 MiB.

This remains the generated-code and compatibility reference.

### TinyCC compact reference

Use the final TinyCC Phase-6/7 qualification from PR #11:

- backend installed payload: about 2.206 MiB;
- cold-JIT ratios: roughly 0.20x-0.29x LLVM-MinGW;
- representative assembly family medians: roughly 1.27x-4.41x LLVM-MinGW.

TinyCC is the compact-footprint reference, not the generated-code reference.

## Size objectives

The initial target range of roughly 30-80 MiB is **aspirational**, not an assumed result.

Measured gates are:

- **early continuation gate:** complete installed backend <= 50% of Stage-AW LLVM-MinGW, approximately 108.2 MiB;
- **strong middle-backend target:** <= 37.5% of Stage AW, approximately 81.2 MiB;
- **stretch target:** <= 25% of Stage AW, approximately 54.1 MiB.

The complete backend measurement must include all compiler executables/DLLs, target headers, startup objects, import libraries, builtins/runtime support, license material, and backend-specific runtime code.

Do not report only clang.exe or only the host-tool directory.

## Performance objectives

micro-Clang is only valuable as a middle option if it preserves LLVM-class generated code.

Against the immutable LLVM-MinGW reference:

- numerical results must remain within existing tolerances;
- representative assembly family aggregate medians should be <= 1.10x LLVM-MinGW;
- no representative interpreter/form case should normally exceed 1.20x without an explicit documented decision;
- representative end-to-end solver behavior must show no material PETSc regression;
- cold JIT should not regress by more than 25% versus LLVM-MinGW and should preferably improve.

If generated-code performance behaves materially differently despite equivalent Clang revisions/options, inspect target CPU/features, optimization flags, linker behavior, builtins, and ABI configuration before accepting the result.

## Main risks

1. **LLVM host-tool floor.** Clang's required frontend/codegen libraries may impose a size floor well above the intended middle range even with a source-minimal build.
2. **Shared-library dependency closure.** A small clang.exe may still require large LLVM/Clang DLLs. The runtime payload must be measured as a complete closure.
3. **Static host linking tradeoff.** A monolithic/self-contained compiler may reduce DLL count but increase executable size, build complexity, and rebuild time.
4. **Windows target sysroot floor.** mingw-w64/UCRT headers and import libraries may dominate once LLVM host tools are minimized.
5. **Over-pruning headers/import libraries.** The current broad sysroot intentionally protects future FFCx-generated C. Aggressive corpus-driven pruning can create latent failures.
6. **Compiler-version drift.** A custom source build must not silently use a different code-generation baseline from the qualified LLVM-MinGW reference.
7. **Bootstrap reproducibility.** Building LLVM is substantially more expensive than packaging TinyCC or pruning a release archive; the exact source/toolchain/build flags must be pinned.
8. **Runtime redistributables.** Host Clang/LLD binaries must not acquire an undeclared Visual C++ runtime or other host dependency that breaks standalone use.
9. **PE/ABI regressions.** Stable-ABI Python linking, UCRT/MinGW startup, exception/unwind metadata, relocations, and mitigation bits must remain at least as strong as the LLVM-MinGW baseline.
10. **Maintenance cost.** Carrying a custom LLVM build is only justified if the size reduction is material and reproducible across upgrades.

## Phases

| Phase | Outcome | Gate |
| --- | --- | --- |
| 0. Baseline decomposition | Measure Stage-AW/current LLVM-MinGW payload by host tools, DLL closure, headers, target libs, runtimes, and metadata | Establish where the 216 MiB is actually spent |
| 1. Source-build feasibility | Reproducibly build X86-only Clang/LLD capable of minimal CFFI and fresh FFCx Poisson JIT | Functional/hermeticity go-no-go |
| 2. Conservative micro-Clang package | Package the source-built compiler with a conservative x86-64 Windows C sysroot | Reproducibility + complete footprint gate |
| 3. Private broad qualification | Run supported Python, broad forms, cache, ABI/PE, concurrency, paths-with-spaces, and MPI without selector/default changes | Viability-before-integration gate |
| 4. Reproducible minimization | Remove unnecessary LLVM components/sysroot content in coherent measured stages | <=108.2 MiB continuation gate; aim <=81.2 MiB |
| 5. Shared-runtime integration and comparison | Add explicit micro-clang selection and run cross-backend functional/size/performance comparison | Isolation + generated-code performance gate |
| 6. Standalone and release decision | Prove hermetic Nuitka/standalone fresh JIT and record final role | Release gate |

Phases are ordered. Production selector/dependency changes may not bypass private qualification.

## Phase 0 requirements

Before building a new toolchain, produce a machine-readable breakdown of the current LLVM-MinGW backend:

- retained host executables;
- host DLL dependency closure;
- Clang resource directory;
- mingw-w64/UCRT headers;
- startup objects;
- import libraries;
- target runtime archives/DLLs;
- backend scripts/metadata/licenses.

Record installed and compressed contribution by category.

This phase should determine whether the likely savings are primarily available from custom-building LLVM, reducing the target sysroot, or both.

## Functional/hermeticity gate

Phase 1 must prove, on supported CPython versions:

- minimal CFFI extension builds/imports;
- fresh FFCx Poisson JIT compiles/imports/assembles/solves;
- only the source-built micro-Clang/LLD tools are invoked;
- no Visual Studio compiler/linker participates;
- no host Windows SDK development input participates;
- no normal LLVM-MinGW backend files are used;
- generated modules import the intended Stable-ABI python3.dll;
- UCRT/Windows imports match the approved policy;
- DLL characteristics include DYNAMIC_BASE, HIGH_ENTROPY_VA, and NX_COMPAT;
- relocations and x64 unwind metadata are present;
- the JIT works with paths containing spaces.

Failure stops the experiment before production runtime integration.

## Package and reproducibility gate

The package must:

- pin exact LLVM and mingw-w64/runtime revisions;
- record exact bootstrap compiler and CMake/Ninja versions;
- record all source checksums and local patches;
- capture CMake/cache configuration used to build the compiler;
- produce a retained-file manifest;
- rebuild reproducibly from a clean work root, with any unavoidable nondeterminism explicitly identified;
- have no runtime dependency on Visual Studio, an external Windows SDK, normal LLVM-MinGW, or TinyCC;
- contain required LLVM/mingw-w64 license notices.

The full package payload, not an intermediate staging subset, is used for size decisions.

## Private broad qualification gate

Before adding micro-Clang to the shared selector, repeat the existing broad qualification matrix using the installed package:

- Python 3.12-3.14 blocking matrix;
- Python 3.15 preview as informational until promoted by repository policy;
- scalar Poisson;
- vector elasticity;
- higher-order P3;
- interior/exterior facet forms;
- coefficient-heavy forms;
- nonlinear residual/Jacobian;
- fem.Expression;
- fresh cache and new-process cache reload;
- numerical comparison to LLVM-MinGW;
- hostile/ambient compiler configuration isolation;
- PE imports/security/unwind inspection;
- thread/concurrent activation semantics where applicable;
- two-rank MPI JIT/cache ownership;
- paths containing spaces.

Use the existing generated-C corpus contract where possible so compiler comparison is against identical inputs.

## Minimization policy

Minimization must be staged and reversible.

For each coherent reduction:

~~~text
conservative source-built package
  -> remove/disable one coherent component family
  -> record bytes/files removed
  -> rebuild package
  -> run complete private qualification
  -> keep or revert
~~~

Candidates include:

- unused LLVM targets accidentally retained;
- LLVM utilities/libraries not required by clang or lld;
- duplicate host DLLs;
- unused Clang tooling/frontends;
- non-Windows resource runtimes;
- sanitizers/profile/fuzzer runtimes;
- C++ target headers/libraries;
- unused import-library families proven unnecessary by both corpus and sentinel coverage.

Do not prune core C/UCRT coverage merely to reach a numerical size target.

## Integration gate

If private qualification and the early size gate pass, add micro-Clang as an explicit shared-runtime backend.

Requirements:

- selector accepts micro-clang only when requested;
- default remains llvm-mingw during evaluation;
- no silent fallback;
- compiler packages retain non-overlapping ownership;
- micro-Clang gets its own cache namespace;
- installing micro-Clang does not require LLVM-MinGW;
- installing LLVM-MinGW does not require micro-Clang;
- side-by-side backend switching passes cache-isolation and concurrency tests.

A default switch is not part of the implementation phase and requires the final release decision.

## Final comparison

Compare all three backends on the same supported Python/form corpus:

| Metric | TinyCC | micro-Clang | LLVM-MinGW |
| --- | --- | --- | --- |
| installed backend footprint | measure | measure | fixed reference |
| compressed package | measure | measure | fixed reference |
| standalone incremental footprint | measure | measure | measure/reference |
| cold JIT | measure | measure | 1.0x |
| warm cache | measure | measure | 1.0x |
| assembly/kernel runtime | measure | measure | 1.0x |
| end-to-end solve | measure | measure | 1.0x |

The comparison should preserve raw distributions/artifacts rather than only averages.

## Standalone gate

The final candidate must perform fresh JIT from the actual standalone/Nuitka layout while:

- the original conda/build prefix is inaccessible;
- Visual Studio/host SDK development inputs are unavailable to the JIT;
- LLVM-MinGW and TinyCC are absent when testing a micro-Clang-only profile;
- all compiler, sysroot, Python/UFCx headers, and import definitions resolve inside the bundle;
- serial fresh compile/cache reuse works;
- the existing two-rank MPI JIT ownership proof works.

## Release decision

Phase 6 must explicitly select one outcome:

- **A — reject:** size reduction or maintenance cost is not compelling, or qualification fails;
- **B — optional middle backend:** micro-Clang is materially smaller and keeps LLVM-class generated-code performance, but LLVM-MinGW remains the normal default;
- **C — default candidate:** micro-Clang passes all gates, is materially smaller, and is sufficiently equivalent to replace LLVM-MinGW in a separate default-switch change;
- **D — standalone/profile backend:** useful only for a particular packaged profile, without changing normal installs.

No automatic default switch occurs merely because this epic qualifies Option C. A separate change must update fenics-dolfinx dependencies/default selection after reviewing final evidence.

## CI policy

Use GitHub-hosted windows-2022 for primary qualification.

During Phases 0-3:

- keep the micro-Clang workflow manual-only or path-scoped to this proposal/implementation;
- do not add costly LLVM source builds to every normal PR;
- cache only immutable bootstrap/source artifacts where provenance remains verifiable;
- upload compiler build configuration, retained-file manifests, size reports, command captures, and PE inspection evidence.

After the conservative package becomes reproducible, prefer reusing a pinned package artifact/channel input for broad functional testing rather than rebuilding LLVM independently in every matrix job.

The normal stack workflow remains the regression authority before any production integration is merged.

## Global acceptance criteria

The experiment succeeds only if:

- the full compiler package is materially smaller than Stage-AW LLVM-MinGW;
- the source build is reproducible and provenance is complete;
- fresh CFFI/FFCx JIT is hermetic and independent of Visual Studio/host SDK development inputs;
- Windows/CPython/UFCx ABI and PE security contracts remain qualified;
- the supported functional, cache, concurrency, and MPI matrices pass;
- generated-code performance remains close to LLVM-MinGW rather than TinyCC-like;
- package ownership/cache identity remain isolated from the other backends;
- standalone fresh JIT succeeds with only the shared runtime + micro-Clang backend;
- the final decision records measured size, cold-JIT, generated-code, maintenance, and release tradeoffs.

Until all of those gates pass, LLVM-MinGW remains the normal/reference backend and TinyCC remains the compact backend.
