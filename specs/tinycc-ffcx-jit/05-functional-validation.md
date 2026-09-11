# Phase 5: broad functional validation

**Status:** proposed.

## Objective

Run the same broad FFCx/CFFI coverage used to qualify LLVM-MinGW, but with the TinyCC backend selected explicitly.

The goal is to discover unsupported generated-C constructs, ABI edge cases, cache problems, MPI behavior differences, and compiler-specific numerical failures before performance/size can influence the decision.

## Required matrix

At minimum reproduce the current LLVM-MinGW Phase 5 coverage:

- standard GIL-enabled CPython 3.12, 3.13, and 3.14;
- standard GIL-enabled Python 3.15 preview when available in the existing CI path;
- fresh JIT and subsequent cache reload;
- scalar Poisson baseline;
- vector/tensor forms;
- cell/interior/exterior-facet forms;
- coefficient/constant-heavy forms;
- representative higher-order elements;
- paths containing spaces;
- two-rank MPI compile/cache semantics;
- PE import/export inspection for generated modules.

Free-threaded CPython is not part of this matrix unless a later proposal explicitly adds its ABI/import-library requirements and qualification cases.

Reuse existing test generation and numerical assertions wherever possible so TinyCC and LLVM-MinGW are compared on exactly the same source/forms.

## Generated-source corpus

Retain every generated C source involved in the matrix as a CI artifact.

For each source record:

- TinyCC compile result;
- compile/link command line;
- warnings/errors;
- source hash;
- Python version;
- form/test identity.

This corpus becomes the compatibility contract for future TinyCC upgrades. A new compiler revision must compile the same corpus before it can replace the pinned revision.

## Numerical equivalence

Compare TinyCC results directly with the existing LLVM-MinGW reference for the same tests.

Require:

- same solve success/failure outcome;
- existing tolerance checks pass unchanged;
- no compiler-specific NaN/Inf behavior;
- no unexplained differences in assembled vectors/matrices or reported error norms.

If a difference is due to floating-point optimization choices, characterize it before relaxing any tolerance. Do not weaken tests merely to make TinyCC pass.

## Stress/repeatability

Add repeated fresh JIT cycles within one process and across new processes to catch compiler/adapter state leakage.

Suggested stress set:

- 100 minimal CFFI compile/load/unload cycles;
- 20 fresh FFCx module compilations across distinct cache keys;
- concurrent MPI ranks hitting one TinyCC cache namespace;
- repeated backend switching LLVM-MinGW -> TinyCC -> LLVM-MinGW.

For every backend transition, prove from diagnostics that the target backend performs at least one fresh compilation in its own physical cache namespace before a same-backend cache hit is accepted.

## Python-link integrity

For every supported Python version and representative JIT module:

- capture the logical libraries and `.def` inputs passed to TinyCC;
- fail if `python312`, `python313`, `python314`, `python315`, or another minor-version Python library is requested;
- inspect PE imports and require `python3.dll` with no minor-version Python DLL;
- verify `Py_NO_LINK_LIB`/header handling did not introduce an implicit Python autolink dependency.

## CRT/allocator stress

If PE inspection shows TinyCC uses a different CRT from the native stack, add explicit stress around:

- buffers crossing CFFI/Python boundaries;
- strings and error paths;
- repeated module load/unload;
- any allocations performed by generated wrappers;
- exception/error handling.

A crash-free small Poisson solve is not sufficient evidence for a mixed-CRT boundary.

## Tasks

1. Parameterize the existing Phase 5 validation for backend selection where practical.
2. Run the full standard GIL-enabled CPython matrix under TinyCC.
3. Preserve generated C and compile/link diagnostics.
4. Compare numerical results with LLVM-MinGW.
5. Add repeated compile/load stress.
6. Validate mandatory physical cache isolation and fresh compilation across backend switches.
7. Validate MPI behavior and cache-root propagation.
8. Validate Stable-ABI link integrity on every supported Python version.
9. Add CRT-boundary stress if required by PE imports.
10. Record unsupported-warning inventory without suppressing it globally.

## Exit criteria

Phase 5 passes when TinyCC completes the full existing functional matrix and stress tests on supported standard GIL-enabled Python versions with no ABI, cache, MPI, Python-link, or numerical regression and with no ambient compiler fallback.
