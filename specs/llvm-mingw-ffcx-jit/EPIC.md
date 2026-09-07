# EPIC: LLVM-MinGW runtime compiler for FFCx JIT on Windows

## Status

**Status:** in progress — Phases 1-3 complete; Phase 4 DOLFINx runtime metadata switch is next.

This epic replaces the Windows runtime Visual Studio compiler dependency used by FFCx/CFFI JIT with a small, self-contained LLVM-MinGW toolchain. It does not change the compiler used to build PETSc, DOLFINx, Basix, or other native packages.

## Goal

Ship a Windows runtime JIT compiler containing only what FFCx/CFFI needs:

- Clang C compiler;
- LLD linker;
- mingw-w64/UCRT headers and import libraries;
- x86-64 target support.

The runtime must work on supported Windows 10/11 systems without Visual Studio, Build Tools, MSYS2, a developer command prompt, or conda compiler activation.

TinyCC remains a possible later fallback or size experiment and is out of scope for this epic.

## Background

The current `fenics-dolfinx` Windows runtime dependency includes the configured C compiler because FFCx uses CFFI to compile generated C code at runtime.

The native FEniCSx stack should continue to use VS2022:

```text
VS2022
  -> PETSc / DOLFINx / Basix / native package builds
```

Only runtime JIT moves to LLVM-MinGW:

```text
UFL
  -> FFCx generated C
  -> CFFI / setuptools build_ext
  -> x86_64-w64-mingw32-clang
  -> LLD
  -> JIT .pyd
  -> DOLFINx
```

The dedicated runtime package is provisionally named:

```text
fenics-jit-llvm-mingw
```

It should not be exposed or activated as a general-purpose compiler environment unless required.

## Phases

| Phase | Spec | Outcome | Gate |
| --- | --- | --- | --- |
| 1 | [Compatibility proof](01-compatibility-proof.md) | Fresh FFCx/CFFI Poisson JIT uses only LLVM-MinGW | Functional go/no-go |
| 2 | [Runtime package](02-runtime-package.md) | Reproducible conservative `fenics-jit-llvm-mingw` package | Package install/JIT proof |
| 3 | [JIT runtime setup](03-jit-runtime-setup.md) | Owned helper resolves compiler/Python development inputs hermetically | Ambient-toolchain independence |
| 4 | [DOLFINx runtime dependency](04-dolfinx-runtime-dependency.md) | `fenics-dolfinx` depends on the JIT package and explicit build backend | Metadata switch gate |
| 5 | [Functional validation](05-functional-validation.md) | Broad forms, cache, MPI, CPython 3.12-3.14 pass | Coverage gate |
| 6 | [Toolchain minimization](06-toolchain-minimization.md) | Reproducibly minimized toolchain meets size target | Size gate |
| 7 | [Standalone/Nuitka staging](07-standalone-nuitka.md) | Standalone bundle performs fresh JIT with build prefix unavailable | Release gate |

Phases are ordered. A later phase may be prototyped early when useful, but its production change must not bypass the exit gate of an earlier dependency.

### Implementation status

Phases 1, 2, and 3 are complete.

Phase 1 proved fresh CFFI and FFCx Poisson JIT on CPython 3.12-3.14 with the
setuptools `mingw32` backend, LLVM-MinGW Clang/LLD, Stable-ABI
`python3.dll` imports, and sanitized Visual Studio/Windows SDK state.

Phase 2 packages the conservative proven toolchain as
`fenics-jit-llvm-mingw`. The package has no runtime dependencies, installs
and compiles in an otherwise empty conda prefix, generates its Python GNU import
libraries during package construction, and passes the same packaged CFFI/FFCx
matrix on CPython 3.12-3.14. A rattler-build rebuild is bit-for-bit identical to
the original package.

Phase 3 packages an owned hermetic runtime helper that resolves compiler,
linker, Python development inputs, UFCx headers, and the setuptools backend
without compiler activation or persistent environment changes. CI poisons
ambient Visual Studio/Windows SDK/compiler variables and verifies the actual
compile/link inputs remain package-relative. The fresh Poisson proof passes on
CPython 3.12-3.14, and a two-rank MPI probe confirms identical JIT
configuration across child processes. Dedicated workflow run #44
(`34094463578`) is green.

Phase 4 may now switch the Windows `fenics-dolfinx` runtime metadata from the
general compiler dependency to `fenics-jit-llvm-mingw` plus an explicit
runtime setuptools/distutils provider, while keeping the native package build
toolchain on VS2022.

## Primary gates

### Functional go/no-go

Phase 1 must prove a fresh `scripts/test-poisson.py` JIT with:

- setuptools compiler backend explicitly selected as `mingw32`;
- packaged LLVM-MinGW Clang/LLD actually invoked;
- FFCx using GNU-driver-compatible flags such as `-std=c17`;
- no MSVC or host Windows SDK compiler/header/library inputs;
- a working CPython import-library strategy.

Failure here stops the epic before package/runtime metadata is changed.

### Metadata switch gate

Before Phase 4 replaces the existing Windows runtime `c-compiler` dependency:

- fresh JIT must pass on CPython 3.12, 3.13, and 3.14;
- the generated `.pyd` PE import table must match the selected Python ABI strategy;
- runtime `setuptools` must be explicit rather than incidental;
- no Visual Studio activation may be required.

### Size gate

The final installed LLVM-MinGW JIT compiler footprint must be **no more than 50% of the installed size of the current Windows runtime compiler dependency closure**, while continuing to pass the full functional matrix.

If it does not meet that threshold, the implementation must not replace the current runtime compiler dependency without an explicit decision explaining why the reduction is still worthwhile.

### Standalone release gate

The standalone/Nuitka bundle must perform a fresh FFCx JIT while:

- the original conda/build prefix is renamed, moved, or otherwise inaccessible;
- Visual Studio and the host Windows SDK are unavailable to the JIT process;
- compiler, CPython headers, Python import library, and setuptools/distutils are resolved from the bundle.

## Cross-phase CI requirements

Use GitHub-hosted `windows-2022` as the primary implementation and verification environment.

Initially keep this work in a dedicated workflow such as:

```text
.github/workflows/llvm-mingw-jit.yml
```

Do not fold the experimental path into `stack.yml` or `channel-dep-test.yml` until the Phase 1 fresh Poisson JIT is reliable.

Because the hosted runner contains Visual Studio and the Windows SDK, CI must prove **non-use**, not physical absence. Fresh JIT tests must:

- replace/sanitize `PATH`;
- clear `VSINSTALLDIR`, `VCINSTALLDIR`, `VCToolsInstallDir`, `VSCMD_*`, `INCLUDE`, `LIB`, `LIBPATH`, Windows SDK, and UCRT activation variables;
- fail if `cl.exe`, MSVC `link.exe`, `vcvarsall.bat`, or `vswhere.exe` are used or discovered by the JIT path;
- record the selected setuptools compiler backend;
- record compiler and linker commands;
- record effective include and library search/input paths;
- fail if JIT inputs resolve below Visual Studio or host Windows Kits/SDK directories;
- clear the FFCx cache for fresh-compilation checks;
- retain compiler/linker/search-path diagnostics as CI artifacts.

The final release test must exercise the minimized package, not only the full upstream LLVM-MinGW archive.

## Global acceptance criteria

The epic is complete when:

- FFCx/CFFI JIT succeeds with MSVC unavailable to the JIT process and logs proving LLVM-MinGW/LLD were used;
- compiler and linker search paths contain no JIT inputs from Visual Studio or the host Windows SDK;
- DOLFINx/PETSc continue to use the existing VS2022 build path;
- Poisson and the broader JIT test matrix pass;
- MPI JIT and cache reuse work;
- the Python import-library strategy is proven on CPython 3.12, 3.13, and 3.14;
- generated `.pyd` files load on all supported CPython runtimes and have expected PE imports;
- the runtime has an explicit setuptools/distutils provider required by CFFI runtime compilation;
- the JIT runtime helper resolves all compiler and Python development inputs without persistent environment modification;
- the runtime compiler is packaged independently from the full development compiler stack;
- minimization is reproducible and every retained component has a documented reason;
- size before/after each minimization stage and incremental standalone bundle size are recorded;
- the final installed compiler footprint meets the 50% size gate;
- the standalone/Nuitka bundle performs fresh JIT with the original build prefix inaccessible.

A one-time test on a genuinely pristine Windows VM with Visual Studio not installed remains useful final release confidence, but is optional and not a prerequisite for implementation or CI acceptance.
