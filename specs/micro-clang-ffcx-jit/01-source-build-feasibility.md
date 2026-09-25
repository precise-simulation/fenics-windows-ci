# Phase 1 source-build feasibility

**Status:** implementation ready for private CI qualification.

Phase 1 deliberately changes only the LLVM host-tool construction while holding the
target side to the exact immutable 20260826 x86-64 UCRT control. It does not add a
production selector value or package dependency.

## Build

`scripts/micro-clang-jit/build-phase1.ps1` checks out LLVM commit
`ea7d852a70e8bdfaf601d6626a760f9771b2c4b4` and configures:

- projects: `clang;lld`;
- LLVM targets: `X86` only;
- shared LLVM dylib: off;
- shared Clang dylib: off;
- host MSVC runtime: static `MultiThreaded`;
- tests/examples/benchmarks/docs: off;
- zlib/zstd/libxml2/terminfo: off;
- default target triple: `x86_64-w64-windows-gnu`.

The staged host tools are source-built `clang-23.exe`, `ld.lld.exe`,
`llvm-dlltool.exe`, and `llvm-readobj.exe`. The same-revision llvm-mingw target
launcher/config and conservative x86-64 UCRT sysroot/resource tree are staged as
the Phase-1 control. Phase 2 owns replacing this control staging with the
conservative package construction.

No `libLLVM-23.dll`, `libclang-cpp.dll`, target C++ runtime DLL, or
libwinpthread DLL is accepted in the host-tool staging directory.

## Private gate

The path-scoped `micro-clang-jit` workflow performs:

1. immutable Phase-0 reference validation;
2. one Windows source build;
3. Python 3.12, 3.13, and 3.14 private JIT proofs reusing that exact stage;
4. target-triple, target CPU/features, MS-bitfield, and `long double` comparison
   against the immutable LLVM-MinGW 20260826 driver;
5. PE mitigation, relocations, x64 unwind, linker-driver, and host-DLL sentinels;
6. Stable-ABI `python3.dll` linking;
7. minimal CFFI and fresh FFCx Poisson compile/import/solve under deliberately
   poisoned Visual Studio/Windows SDK environment variables;
8. a toolchain path containing spaces.

The shared `fenics-jit-runtime` selector is intentionally unchanged. A Phase-1
failure blocks package work and production integration.
