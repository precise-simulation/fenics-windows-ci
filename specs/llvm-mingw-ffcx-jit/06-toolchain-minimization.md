# Phase 6: minimize the toolchain

**Status:** in progress — Phase 5 is green; the conservative package baseline is recorded before reproducible pruning begins.

## Objective

Reduce the conservative Phase 2 LLVM-MinGW runtime package to the smallest maintainable subset that still passes the complete Phase 5 validation matrix.

Minimization must be reproducible rather than hand-pruned.

## Size baseline

Phase 5 stack run #160 (`34125754984`) records the conservative LLVM-MinGW package at:

- staged JIT payload: **465.10 MiB**;
- conda package installed content: **466.91 MiB**;
- compressed `.conda` artifact: **86.91 MiB**.

The previous Windows runtime compiler dependency closure baseline and standalone-bundle increment still need to be measured before evaluating the 50% gate.

Before removing files, record:

- installed size of the current Windows compiler dependency closure pulled into a `fenics-dolfinx` runtime environment;
- compressed package/download size attributable to that compiler closure where measurable;
- installed and compressed size of the conservative LLVM-MinGW JIT package;
- incremental size the conservative toolchain would add to the standalone bundle.

After every reduction stage record:

- installed size;
- compressed package size;
- retained-file manifest.

## Size gate

The final LLVM-MinGW JIT compiler footprint must be **no more than 50% of the installed size of the current Windows runtime compiler dependency closure** while passing the full functional matrix.

If the target is not met, do not replace the existing runtime dependency without an explicit decision.

## Reproducible reduction

Implement a script such as:

```text
scripts/minimize-jit-toolchain.ps1
```

For each coherent reduction:

```text
working package
  -> remove one coherent file group
  -> record size
  -> run full JIT tests
  -> inspect JIT .pyd dependencies
  -> keep or revert the reduction
```

Upload size reports, retained-file manifests, compiler/linker logs, and the minimized toolchain as workflow artifacts.

## Stage A: remove non-x86-64 targets

**Implementation:** build 1 applies this reduction reproducibly via
`recipes/fenics-jit-llvm-mingw/minimize-toolchain.ps1`. It removes all
AArch64, ARM64EC, ARMv7, and i686 driver/tool aliases from the staged `bin`
tree, asserts that no unsupported target sysroot was staged, and writes a
before/after removal report. Stack run #162 (`34129806540`) passed the full
Phase 5 matrix. Stage A removed **184 files / 7.92 MiB**; the final package
changed from **466.91 to 458.96 MiB installed** and from **86.91 to 86.85 MiB
compressed**.

Remove target-specific files for unsupported architectures, as applicable:

- i686;
- ARMv7;
- AArch64;
- ARM64EC.

Retain only x86-64.

Run the full validation matrix.

## Stage B: remove C++ support

**Implementation:** build 2 extends the same reproducible minimizer to remove
the libc++ header tree, libc++/libc++abi target files, libunwind headers,
dynamic target libunwind files, and C++ driver aliases. The runtime helper pins
both `CC` and `CXX` to the packaged Clang C driver so setuptools cannot
fall back to a host C++ compiler.

Run #163 (`34133171394`) established an important boundary before the package
smoke test: plain x86-64 Clang C shared-library links pass `-lunwind`, so
`x86_64-w64-mingw32/lib/libunwind.a` is required and is retained. Separately,
the LLVM executables themselves depend on the root `bin/libc++.dll` and
`bin/libunwind.dll`; these are compiler-tool runtime dependencies rather than
generated-FFCx C++ support and are also retained. Stack run #164
(`34136483104`) passed the complete Phase 5 gate. Corrected Stage B removed
**1708 files / 19.35 MiB** on top of Stage A; the package is now **439.49 MiB
installed / 83.98 MiB compressed**.

FFCx JIT generates C only.

Remove where tests prove unnecessary:

- libc++;
- libc++abi;
- C++ headers;
- C++ driver aliases;
- C++ target libraries;
- C++ exception/unwind support not required by C runtime use.

Retain compiler-rt builtins required by generated C.

Run the full validation matrix.

## Stage C: remove unused LLVM tools

**Implementation:** build 3 keeps only the executable path required by current
JIT/package validation: `x86_64-w64-mingw32-clang.exe`, `clang-23.exe`,
`ld.lld.exe`, `llvm-readobj.exe`, and `llvm-dlltool.exe`. Other
executables are removed reproducibly. LLDB-only `liblldb`, Python/FFI DLLs,
and the root OpenMP runtime are also removed because the retained executable
dependency graph does not reference them. Shared LLVM/Clang/libc++/libunwind
DLLs needed by the retained compiler tools remain. Full Phase 5 validation is
pending for Stage C.

Use observed JIT invocations plus `clang -###` to identify actual requirements.

Likely retained components:

- Clang driver/front-end;
- LLD component used by the driver;
- Clang resource headers;
- target C headers/import libraries;
- required compiler-rt pieces.

Removal candidates, when proven unused:

- `clang++`;
- `clang-cl`;
- debugger tools;
- `llvm-ar`;
- `llvm-nm`;
- `llvm-objdump`;
- `llvm-readobj`;
- `llvm-rc`;
- `llvm-ranlib`;
- `llvm-dlltool`;
- OpenMP;
- sanitizers;
- profiling tools.

Do not remove tools based only on name.

## Stage D: minimize target libraries conservatively

Candidates:

- C++ libraries;
- sanitizer runtimes;
- profiling runtimes;
- unsupported-architecture libraries;
- duplicate/static libraries not referenced by representative JIT links.

Keep UCRT/mingw-w64 C headers and import libraries conservative unless size measurements show a compelling benefit. Future FFCx-generated C may exercise standard-library functions absent from a minimal Poisson case.

## Stage E: strip shipped binaries

Strip compiler/linker binaries during package construction where safe.

Do not ship the stripping tool unless otherwise required.

Do not use executable compressors such as UPX.

## Exit criteria

Phase 6 is complete when:

- minimization is generated by a reproducible script;
- every retained component has a documented reason;
- every reduction stage has size and test evidence;
- the minimized package passes the full Phase 5 matrix;
- generated `.pyd` dependency inspection remains clean;
- the final installed footprint meets the 50% size gate.
