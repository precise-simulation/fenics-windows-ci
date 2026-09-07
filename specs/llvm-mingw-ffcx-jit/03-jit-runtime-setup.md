# Phase 3: JIT runtime setup

**Status:** complete — hermetic runtime helper and MPI configuration proof pass on GitHub `windows-2022`.

## Objective

Provide a small owned runtime helper that makes FFCx/CFFI compiler discovery deterministic and independent of ambient compiler or Python-development state.

## Responsibilities

The helper must provide or control:

- setuptools compiler backend: `mingw32`;
- LLVM-MinGW C compiler executable;
- Clang/LLD target and relevant compile/link flags;
- CPython include directory containing `Python.h` and `pyconfig.h`;
- directory and logical name of the GNU Python import library;
- FFCx/UFCx include directory;
- packaged mingw-w64/UCRT include and library roots as required.

For normal conda installs, paths may resolve into the active prefix.

For standalone/Nuitka, paths must resolve into staged bundle directories. Copying headers/import libraries beside the executable is not sufficient: the helper must pass those paths into CFFI/setuptools so `build_ext` cannot fall back to development files in the original build prefix.

## Environment behavior

The helper must:

- be process-local/JIT-local;
- not modify the user's persistent environment;
- not require shell activation;
- not query Visual Studio, Windows SDK, or registry compiler state;
- work for serial and MPI child processes.

When verbose JIT logging is enabled, report enough information to diagnose selection, for example:

```text
FFCx JIT compiler: LLVM-MinGW / Clang <version> / mingw32 / x86_64 / UCRT
FFCx JIT Python: <include-root> / python3.dll
```

## Integration preference

Prefer the narrowest maintainable integration:

1. helper/configuration around existing CFFI/setuptools APIs;
2. small FFCx/CFFI patch;
3. custom compile/link adapter only if the existing backend cannot be made deterministic.

Avoid globally changing Python's build compiler configuration.

## Implementation result

The owned helper is packaged as:

```text
Library/fenics-jit/runtime/fenics_jit_runtime.py
```

It resolves the packaged LLVM-MinGW compiler, linker, mingw-w64/UCRT roots,
Python headers, package-built GNU Python import library, and FFCx/UFCx headers
relative to the active runtime or explicit staged roots.

CFFI/setuptools compiler selection is owned in-process through the temporary
CFFI `Distribution` object. Ambient `setup.cfg` / `pydistutils.cfg`
compiler choices are ignored for JIT builds, and the helper forces the
`mingw32` backend without globally changing Python's build configuration.

The helper applies JIT-local environment changes only for the duration of the
compile/load operation and restores the process afterwards. It preserves the
active conda runtime DLL/MPI search paths needed by DOLFINx while removing
Visual Studio and Windows SDK directory inputs from the JIT path. CI
deliberately poisons VS/SDK/compiler variables and verifies the actual compiler
and linker command logs still use the packaged Clang/LLD and helper-selected
include/library roots.

The helper also emits resolved configuration diagnostics including:

- compiler/backend/target/CRT;
- Clang and LLD versions;
- Python include root and `python3.dll`;
- packaged Python GNU import library;
- FFCx/UFCx include root;
- mingw-w64/UCRT include and target-library roots.

Dedicated workflow run #44
(`34094463578`) passed on CPython 3.12, 3.13, and 3.14. The fresh Poisson
proof generated three JIT modules and retained the expected L2 error
(`0.009053553714812534`). On CPython 3.12, a two-rank MPI child-process
probe confirmed both ranks selected an identical runtime JIT configuration.

## Tasks

1. [x] Implement runtime-relative toolchain discovery.
2. [x] Implement Python include/import-library discovery for the chosen ABI strategy.
3. [x] Own JIT-local setuptools backend selection.
4. [x] Apply compiler-specific FFCx flags through the same selection path.
5. [x] Ensure MPI-launched child processes receive the same deterministic JIT configuration.
6. [x] Add verbose diagnostic output.
7. [x] Add tests that poison or remove ambient VS/SDK variables and verify correct runtime-relative resolution.

## Exit criteria

Phase 3 is complete when:

- normal conda runtime JIT requires no compiler activation;
- all compiler/Python development inputs are selected by the owned helper;
- poisoned ambient compiler/SDK state cannot redirect the JIT;
- MPI child processes use the same toolchain configuration;
- the helper is suitable for reuse by the standalone bundle in Phase 7.

All Phase 3 exit criteria are satisfied by dedicated workflow run #44.
