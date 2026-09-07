# Phase 3: JIT runtime setup

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

## Tasks

1. Implement runtime-relative toolchain discovery.
2. Implement Python include/import-library discovery for the chosen ABI strategy.
3. Own JIT-local setuptools backend selection.
4. Apply compiler-specific FFCx flags through the same selection path.
5. Ensure MPI-launched child processes receive the same deterministic JIT configuration.
6. Add verbose diagnostic output.
7. Add tests that poison or remove ambient VS/SDK variables and verify correct runtime-relative resolution.

## Exit criteria

Phase 4 is complete when:

- normal conda runtime JIT requires no compiler activation;
- all compiler/Python development inputs are selected by the owned helper;
- poisoned ambient compiler/SDK state cannot redirect the JIT;
- MPI child processes use the same toolchain configuration;
- the helper is suitable for reuse by the standalone bundle in Phase 7.
