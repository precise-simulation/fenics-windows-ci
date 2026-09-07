# Phase 2: dedicated runtime package

**Status:** complete — packaged compatibility proof passed on GitHub `windows-2022` for CPython 3.12, 3.13, and 3.14.

## Objective

Package a conservative, reproducible LLVM-MinGW subset dedicated to FFCx/CFFI runtime JIT.

Do not minimize aggressively in this phase. First package the known-working Phase 1 toolchain.

## Package

The package is:

```text
fenics-jit-llvm-mingw
```

The initial conservative layout is:

```text
Library/
  fenics-jit/
    bin/
    include/
    lib/
      clang/<version>/
      python/
        python3.def
        libpython3.a
        libpython312.a
        libpython313.a
        libpython314.a
    x86_64-w64-mingw32/
      bin/
      lib/
      share/
```

LLVM-MinGW's Windows cross-toolchain layout keeps the mingw-w64/UCRT headers at
the toolchain-root `include/` directory. Architecture-specific runtime/import
libraries remain under `x86_64-w64-mingw32/`.

## Package metadata

Pinned and recorded:

- LLVM-MinGW release: `20260826`;
- LLVM/Clang version: `23.1.0`;
- upstream archive:
  `llvm-mingw-20260826-ucrt-x86_64.zip`;
- upstream archive SHA-256:
  `ae601f4e0f72bbdf441ad2df8bb16f037e2e9251559ea6b37b4057aef39c06c3`;
- target: `x86_64-w64-mingw32` (Clang reports
  `x86_64-w64-windows-gnu`);
- CRT: UCRT.

The package has no runtime dependencies and does not require:

- Visual Studio;
- Windows SDK installation;
- MSYS2;
- compiler activation scripts.

## Contents

The first package intentionally contains a conservative working set rather than
the final minimized set:

- Clang driver/front-end;
- LLD;
- Clang resource headers;
- mingw-w64/UCRT headers;
- x86-64 target/runtime/import libraries;
- compiler-rt/runtime pieces supplied by upstream LLVM-MinGW;
- Python GNU import libraries generated at package construction time.

The version-named Python GNU import libraries deliberately target
`python3.dll`, preserving the Phase 1 Stable-ABI strategy across CPython
3.12-3.14.

Helper tools are not yet aggressively removed. Phase 6 owns measured pruning
after the packaged functional path is established.

## Implementation result

The package recipe lives in:

```text
recipes/fenics-jit-llvm-mingw/
```

The dedicated CI workflow:

1. builds the package with rattler-build;
2. verifies the package declares no runtime dependencies;
3. installs it into an otherwise empty conda prefix;
4. compiles a DLL from that clean prefix;
5. rebuilds the emitted package from its embedded rendered recipe;
6. requires original and rebuilt package SHA-256 values to match exactly;
7. installs the exact package artifact into isolated FEniCS environments;
8. runs the Phase 1 minimal CFFI and fresh Poisson FFCx proofs on CPython
   3.12, 3.13, and 3.14.

The reproducibility check passes bit-for-bit. Rattler-build's rebuild path reuses
the exact solved build dependencies and original build timestamp /
`SOURCE_DATE_EPOCH` embedded in the package.

Initial conservative package measurements are:

| Metric | Value |
| --- | ---: |
| Files | 5,508 |
| Installed payload | 465.08 MiB |
| Compressed `.conda` | 86.90 MiB |

These values are the Phase 2 baseline for later minimization. They are not a
size target.

Fresh packaged FFCx Poisson JIT passes on CPython 3.12, 3.13, and 3.14 under
the sanitized Phase 1 environment. The proof records the `mingw32`
setuptools backend, LLVM-MinGW compiler/linker commands, PE imports, and
search-path diagnostics and continues to reject Visual Studio / host Windows
SDK JIT inputs.

## Tasks

1. [x] Add the runtime package recipe.
2. [x] Fetch the pinned upstream LLVM-MinGW archive reproducibly.
3. [x] Stage the conservative x86-64 runtime/compiler tree.
4. [x] Generate required Python import-library artifacts at package construction
   time.
5. [x] Record file manifest and installed/compressed package size.
6. [x] Install the package into a clean test environment.
7. [x] Re-run the Phase 1 fresh Poisson JIT under the sanitized environment.
8. [x] Verify bit-for-bit reproducibility with `rattler-build rebuild`.

## Exit criteria

Phase 2 is complete:

- the package builds reproducibly on the hosted Windows runner;
- a clean environment installs it without a general-purpose compiler activation
  package;
- fresh FFCx Poisson JIT passes using package contents plus the Python/FEniCS
  runtime on CPython 3.12-3.14;
- package contents, versions, source checksum, manifest, and initial size are
  recorded.

Phase 3 should now replace the prototype JIT setup with an owned hermetic runtime
helper before changing `fenics-dolfinx` runtime metadata.
