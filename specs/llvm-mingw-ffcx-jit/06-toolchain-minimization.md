# Phase 6: minimize the toolchain

**Status:** complete — reproducible minimization and the measured 50% size gate are green in stack run #171 (`34186723562`).

## Objective

Reduce the conservative Phase 2 LLVM-MinGW runtime package to the smallest maintainable subset that still passes the complete Phase 5 validation matrix.

Minimization must be reproducible rather than hand-pruned.

## Size baseline

Phase 5 stack run #160 (`34125754984`) records the conservative LLVM-MinGW package at:

- staged JIT payload: **465.10 MiB**;
- conda package installed content: **466.91 MiB**;
- compressed `.conda` artifact: **86.91 MiB**.

The previous Windows runtime compiler was not self-contained: on Windows,
`${{ compiler("c") }}` resolved to the small `vs2022_win-64` activation
package, which locates and activates an externally installed Visual Studio
2022/Windows SDK toolchain. Therefore the conda activation package size is not
a valid denominator for the 50% gate.

`scripts/llvm-mingw-jit/measure-vs2022-jit-baseline.ps1` now measures the
external compiler prerequisite on the same `windows-2022` runner. It records:

- a deliberately conservative **x64 C JIT lower bound** consisting of the
  VS2022 x64 compiler/linker bin tree, MSVC headers and x64 libraries, VC
  activation files, and the selected Windows SDK x64 tools, UCRT/shared/UM
  headers, and UCRT/UM x64 libraries;
- the broader activated `INCLUDE`/`LIB` search closure for comparison;
- the complete versioned MSVC toolset plus selected Windows SDK version roots
  as contextual installed-prerequisite data.

The 50% decision uses the conservative x64 C JIT lower bound, not the broader
Visual Studio installation. External Visual Studio download/compressed bytes
are not meaningfully attributable on the pre-baked GitHub runner, so they are
reported as not measurable rather than substituting the tiny conda activation
package. The exact standalone bundle delta remains a Phase 7 measurement.

Stack run #171 (`34186723562`) measured:

- x64 C JIT lower bound: **1297.04 MiB**;
- activated `INCLUDE`/`LIB` closure: **2011.46 MiB**;
- broader installed prerequisite context: **13592.70 MiB**;
- 50% lower-bound gate ceiling: **648.52 MiB**.

The minimized LLVM-MinGW staged compiler payload is **297.52 MiB**, or
**22.94%** of the conservative lower bound. The packaged installed size reported
by rattler-build is **298.65 MiB**, or **23.03%** of that lower bound. Both are
well below the required 50% ceiling.

CI measures the VS2022 lower bound before package construction, exports the
resulting gate threshold, and the staging recipe fails if the staged runtime
compiler payload exceeds it. This keeps the size gate executable rather than
documentation-only.

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
DLLs needed by the retained compiler tools remain. Stack run #165
(`34172969848`) passed the complete Phase 5 gate. Stage C removed **93 files /
53.55 MiB** on top of Stages A-B; the package is now **385.94 MiB installed /
68.63 MiB compressed**.

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

**Implementation:** build 4 first prunes the compiler resource-runtime side
without touching the conservative mingw-w64/UCRT import-library set. It removes
the complete Clang Linux runtime tree and every Windows Clang sanitizer,
profiling, fuzzer, ORC, and unsupported-architecture archive, retaining only
`lib/clang/23/lib/windows/libclang_rt.builtins-x86_64.a`. Run #165 showed
these resource-runtime trees account for roughly **85 MiB** before this stage.
Stack run #166 (`34175304551`) passed the complete Phase 5 gate. Stage D
removed **118 files / 84.92 MiB**; the package is now **301.02 MiB installed /
56.70 MiB compressed**.

Candidates:

- C++ libraries;
- sanitizer runtimes;
- profiling runtimes;
- unsupported-architecture libraries;
- duplicate/static libraries not referenced by representative JIT links.

Keep UCRT/mingw-w64 C headers and import libraries conservative unless size measurements show a compelling benefit. Future FFCx-generated C may exercise standard-library functions absent from a minimal Poisson case.

## Stage E: strip shipped binaries

**Implementation:** build 5 temporarily retains `llvm-strip.exe` during
minimization, copies the stripping tool plus its required local DLLs to a
temporary directory so Windows does not lock shipped DLLs while they are being
rewritten, applies `llvm-strip --strip-debug` to retained PE executables and
DLLs in the compiler and x86-64 target runtime `bin` trees, records per-file
before/after sizes, verifies no file grows, and removes `llvm-strip.exe` from
the package.

Stack run #168 (`34182210924`) passed the complete Phase 5 matrix and the
Python 3.15 preview. Stage E stripped **14 files / 2.38 MiB**, and removal of
the build-only `llvm-strip.exe` accounts for another **0.18 MiB**. The
minimized payload is **296.20 MiB** before post-minimization staging additions;
the final staged package payload is **297.52 MiB**. The finished package is
**298.65 MiB installed / 56.00 MiB compressed**.

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

All exit criteria are satisfied. Stack #171 passed the complete Phase 5 matrix,
Python 3.15 preview, and the measured size gate. Further mingw-w64/UCRT
import-library pruning is intentionally not pursued: the current package already
uses only about 23% of the conservative old-runtime lower bound, while broader
C library coverage reduces the risk that future FFCx-generated forms require an
import library absent from the test matrix.
