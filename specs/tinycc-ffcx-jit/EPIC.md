# EPIC: TinyCC runtime compiler alternative for FFCx JIT on Windows

## Status

**Status:** proposed — experimental alternative to the qualified LLVM-MinGW runtime JIT path.

The current Windows FFCx/CFFI runtime compiler is the bundled LLVM-MinGW package. This epic investigates whether TinyCC (TCC) can provide a much smaller self-contained alternative without changing the VS2022 toolchain used to build PETSc, DOLFINx, Basix, or other native packages.

TinyCC remains opt-in until all functional, ABI, performance, packaging, and licensing gates pass. LLVM-MinGW remains the reference implementation and fallback throughout this work.

## Goal

Provide a package provisionally named:

```text
fenics-jit-tinycc
```

containing only what FFCx/CFFI needs to create Windows `.pyd` modules at runtime:

- x86-64 Windows `tcc.exe`;
- minimal TinyCC runtime/include support;
- required Windows import-definition files (`.def`), including a Stable-ABI `python3.dll` definition;
- an owned setuptools/CFFI compiler adapter;
- a hermetic runtime helper compatible with the existing FEniCS Windows JIT setup.

This is a dedicated FFCx JIT backend, not a general-purpose conda compiler environment.

## Architecture

TinyCC is not a drop-in executable replacement for `x86_64-w64-mingw32-clang` under setuptools' `mingw32` backend. The Windows port can emit DLLs directly with `tcc -shared`, but it uses its own compile/link model and Windows `.def` import definitions. Use an owned TinyCC `CCompiler` adapter plus the smallest required CFFI `build_ext` integration rather than pretending TinyCC is GCC/Clang.

```text
UFL
  -> FFCx generated C
  -> CFFI generated wrapper C
  -> owned TinyCC setuptools/distutils adapter
  -> tcc.exe compile/link
  -> JIT .pyd
  -> DOLFINx
```

Keep both backends selectable during qualification:

```text
FENICS_JIT_COMPILER=llvm-mingw   # current reference/default
FENICS_JIT_COMPILER=tinycc       # experimental
```

## Main risks

1. **C language coverage** — prove the exact pinned TinyCC revision against the actual CFFI/FFCx generated-source corpus. Unsupported C semantics are a Phase 1 stop condition.
2. **Windows ABI compatibility** — TCC-generated x86-64 PE code must interoperate with MSVC-built CPython/DOLFINx. Compare UFCx layout/calling-convention probes with the working LLVM-MinGW path. Preserve `__STDC_NO_COMPLEX__` unless a stronger ABI proof permits otherwise.
3. **Python linking** — use a package-built `python3.def` targeting Stable-ABI `python3.dll`; explicitly suppress setuptools' native-Windows versioned `pythonXY` library selection and disable/verify absence of CPython header-driven library autolinking. CI must reject any versioned Python library request or PE import.
4. **CRT boundary** — record actual CRT/system DLL imports. If TinyCC uses a different CRT from CPython/DOLFINx, audit allocation/file-handle ownership and either prove the boundary safe or configure the package to use the required CRT.
5. **Generated-code performance** — TinyCC should compile very quickly, but its generated code may be slower. Kernel/assembly execution must be benchmarked against LLVM-MinGW before any default switch.
6. **Setuptools/CFFI integration** — own compiler selection in-process; do not depend on global config or masquerade as the `mingw32` backend. Treat CFFI's `_shimmed_dist_utils` and setuptools' compiler discovery as a versioned integration boundary with explicit runtime dependencies and compatibility tests.
7. **Cache identity** — LLVM-MinGW and TinyCC artifacts must never share a physical FFCx/CFFI cache namespace. Backend-specific cache roots are mandatory during qualification.
8. **Licensing** — TinyCC is LGPL-2.1; ship required notices/license material and satisfy source/modification distribution obligations before release.

## Upstream baseline

Do not assume the 2017 `0.9.27` Windows binary is the best baseline. The current TinyCC development branch has recent Win64/PE work. Phase 1 should pin an exact upstream development commit and checksum, while also recording whether the latest formal release passes the same proof. No moving branch/tag is acceptable in a reproducible package.

## Phases

| Phase | Spec | Outcome | Gate |
| --- | --- | --- | --- |
| 1 | [Compatibility proof](01-compatibility-proof.md) | Minimal CFFI + fresh FFCx Poisson JIT works with only TinyCC | Functional/ABI go-no-go |
| 2 | [Runtime package](02-runtime-package.md) | Reproducible `fenics-jit-tinycc` package | Package gate |
| 3 | [CFFI compiler adapter](03-cffi-adapter.md) | Owned TinyCC backend integrates hermetically with CFFI/setuptools | Integration gate |
| 4 | [Runtime integration](04-runtime-integration.md) | Side-by-side backend selection without changing the default | Isolation gate |
| 5 | [Functional validation](05-functional-validation.md) | Existing broad JIT matrix passes under TinyCC | Coverage gate |
| 6 | [Size and performance comparison](06-size-performance-comparison.md) | TinyCC tradeoffs measured against LLVM-MinGW | Decision gate |
| 7 | [Standalone and release decision](07-standalone-release-decision.md) | Standalone proof plus explicit fallback/default/no-ship decision | Release gate |

Phases are ordered. No runtime metadata/default switch may bypass an earlier gate.

## Primary gates

### Functional/ABI gate

Stop if the following cannot be made reliable with a small maintainable adapter:

- minimal CFFI extension compiles/imports on standard GIL-enabled CPython 3.12-3.14;
- fresh FFCx Poisson JIT compiles, imports, assembles, and solves;
- no Visual Studio, host Windows SDK, GCC, Clang, or external linker participates;
- generated `.pyd` imports the intended `python3.dll` Stable ABI;
- no TinyCC link command requests `python312`, `python313`, `python314`, or another minor-version Python library, and no resulting PE imports a minor-version Python DLL;
- UFCx ABI probes match the MSVC/LLVM-MinGW reference;
- the generated C corpus does not require unsupported compiler semantics.

Python 3.15 preview qualification covers the standard GIL-enabled build only unless free-threaded Python is added later as a separate ABI/import-library qualification target.

### Size gate

Use the qualified LLVM-MinGW Stage AW package as the reference:

- installed content: **216.43 MiB**;
- compressed `.conda`: **51.34 MiB**.

TinyCC should be no more than **25% of the LLVM-MinGW installed footprint** (about 54 MiB) to justify proceeding past Phase 6. Record compressed size separately. A stretch objective is a single-digit-MiB dedicated runtime payload.

### Runtime performance gate

Measure both JIT latency and generated kernel/assembly performance.

- **default candidate:** representative assembly/runtime performance within 25% of LLVM-MinGW, with no numerical/stability regression;
- **fallback/compact candidate:** may be slower but should normally remain within 3x LLVM-MinGW on representative kernels while offering a compelling footprint reduction;
- **reject:** severe/highly variable slowdown, ABI instability, or compiler-specific failures make the size saving not worthwhile.

These thresholds guide the decision; inspect the benchmark distribution rather than only an average.

## CI policy

Use GitHub-hosted `windows-2022`. Add a dedicated **manual-only** workflow such as `.github/workflows/tinycc-jit.yml` until the experiment is proven. Keep `.github/workflows/stack.yml` as the only automatic PR/main workflow.

Because the runner contains Visual Studio and the Windows SDK, CI must sanitize the JIT process and prove non-use of host compiler/SDK inputs.

## Global acceptance criteria

The epic is successful when:

- an exact pinned TinyCC revision builds reproducibly;
- the package has no runtime dependency on an external compiler/linker;
- `cffi` and `setuptools` are explicit runtime dependencies with a tested compatibility contract for the private CFFI/distutils integration used by the adapter;
- CFFI/FFCx JIT works on supported CPython runtimes through an owned TinyCC adapter;
- generated modules use the intended Python Stable ABI, no minor-version Python link dependency is requested, and PE imports are audited;
- UFCx ABI compatibility is proven;
- the full existing FFCx functional matrix, backend-isolated cache behavior, paths-with-spaces, and MPI semantics pass;
- numerical results match the LLVM-MinGW reference;
- size and compile/runtime performance are measured side-by-side;
- a standalone bundle performs fresh JIT with the original prefix unavailable;
- an explicit decision records whether TinyCC is a fallback, compact standalone backend, default backend, or rejected.

No automatic replacement of LLVM-MinGW is part of this plan.
