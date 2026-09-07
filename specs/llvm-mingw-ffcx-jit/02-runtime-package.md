# Phase 2: dedicated runtime package

## Objective

Package a conservative, reproducible LLVM-MinGW subset dedicated to FFCx/CFFI runtime JIT.

Do not minimize aggressively in this phase. First package the known-working Phase 1 toolchain.

## Package

Provisionally:

```text
fenics-jit-llvm-mingw
```

Initial layout may follow:

```text
Library/
  fenics-jit/
    bin/
    lib/
    x86_64-w64-mingw32/
      include/
      lib/
    lib/clang/<version>/
```

## Package metadata

Pin and record:

- LLVM-MinGW release;
- LLVM/Clang version;
- upstream archive URL;
- archive checksum;
- target: `x86_64-w64-mingw32`;
- CRT: UCRT.

The package must not require:

- Visual Studio;
- Windows SDK installation;
- MSYS2;
- compiler activation scripts.

## Contents

The first package should contain the conservative working set established in Phase 1, including as required:

- Clang driver/front-end;
- LLD;
- Clang resource headers;
- x86-64 mingw-w64/UCRT headers;
- x86-64 target/import libraries;
- compiler-rt pieces needed by generated C;
- Python GNU import libraries selected by the Phase 1 ABI strategy, if they belong in this package.

Keep helper tools used only during package construction out of the runtime when possible.

## Tasks

1. Add the runtime package recipe.
2. Fetch the pinned upstream LLVM-MinGW archive reproducibly.
3. Stage only the conservative x86-64 runtime/compiler tree.
4. Generate required Python import-library artifacts at package construction time.
5. Record file manifest and installed/compressed package size.
6. Install the package into a clean test environment.
7. Re-run the Phase 1 fresh Poisson JIT under the sanitized environment.

## Exit criteria

Phase 2 is complete when:

- the package builds reproducibly on the hosted Windows runner;
- a clean environment can install it without a general-purpose compiler activation package;
- fresh FFCx Poisson JIT passes using only package contents plus the Python/FEniCS runtime;
- package contents, versions, checksum, and initial size are recorded.
