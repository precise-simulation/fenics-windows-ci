# Phase 5: functional validation

## Objective

Demonstrate that the conservative packaged LLVM-MinGW JIT path covers representative FFCx/DOLFINx runtime compilation, cache behavior, MPI behavior, supported CPython versions, and non-trivial paths.

Run this phase before toolchain minimization.

## Test matrix

At minimum cover:

1. existing P1 Poisson solve;
2. P2 Poisson;
3. vector linear elasticity;
4. cell integrals;
5. exterior-facet integrals / Neumann terms;
6. coefficients and `Constant` values;
7. nonlinear residual and Jacobian forms;
8. `fem.Expression`;
9. JIT cache creation and reload;
10. two-rank MPI JIT, verifying rank-0 compilation and cache load on the other rank;
11. CPython 3.12, 3.13, and 3.14;
12. install and cache paths containing spaces.

## Dependency inspection

For generated JIT `.pyd` files:

- inspect PE imports;
- verify the selected Python DLL strategy;
- verify no unexpected compiler runtime DLL dependency;
- verify the extension does not require an installed LLVM-MinGW environment at load time.

## Fresh-cache discipline

For each fresh-cache test:

- sanitize the process environment as defined by the epic;
- clear the relevant FFCx cache;
- retain verbose compiler/linker logs;
- fail on fallback to MSVC or host SDK inputs.

Then separately test cache reuse without recompilation.

## MPI

The two-rank test must prove:

- rank 0 performs the required compilation;
- the compiled artifact becomes visible through the expected cache path;
- the other rank loads the artifact without starting an independent incompatible compile;
- MPI child environments preserve the JIT runtime helper configuration.

## Tasks

1. Add representative form tests that are not already covered.
2. Add fresh-cache and cache-reload modes.
3. Add two-rank MPI JIT coverage.
4. Matrix the workflow over CPython 3.12-3.14.
5. Add paths-containing-spaces coverage.
6. Add PE dependency inspection.
7. Upload JIT logs and dependency reports as CI artifacts.

## Exit criteria

Phase 5 is complete when the full conservative runtime package passes the complete matrix with:

- no MSVC/host SDK fallback;
- correct Python DLL imports;
- no unexpected compiler runtime dependencies;
- successful cache reuse;
- successful two-rank MPI behavior.
