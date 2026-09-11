# EPIC: TinyCC runtime compiler alternative for FFCx JIT on Windows

## Status

**Status:** proposed — experimental alternative to the qualified LLVM-MinGW runtime JIT path.

The current Windows FFCx/CFFI runtime compiler is the bundled LLVM-MinGW package. This epic investigates whether TinyCC (TCC) can provide a much smaller self-contained alternative without changing the VS2022 toolchain used to build PETSc, DOLFINx, Basix, or other native packages.

TinyCC remains opt-in until all functional, ABI, security, performance, packaging, and licensing gates pass. LLVM-MinGW remains the reference implementation and fallback throughout this work.

## Goal

Provide a package provisionally named:

```text
fenics-jit-tinycc
```

containing only what FFCx/CFFI needs to create Windows `.pyd` modules at runtime:

- x86-64 Windows `tcc.exe`;
- minimal TinyCC runtime/include support;
- required Windows import-definition files (`.def`), including a Stable-ABI `python3.dll` definition;
- an owned TinyCC setuptools/CFFI compiler adapter;
- backend metadata and diagnostics support.

This is a dedicated FFCx JIT backend, not a general-purpose conda compiler environment.

## Runtime ownership and package layout

Side-by-side backends must not own the same runtime-helper files.

Before Phase 4 completes, factor the common Windows JIT selector/lifecycle code into one uniquely owned runtime component, provisionally:

```text
fenics-jit-runtime
  Library/fenics-jit/runtime/...

fenics-jit-llvm-mingw
  Library/fenics-jit/backends/llvm-mingw/...

fenics-jit-tinycc
  Library/fenics-jit/backends/tinycc/...
```

`fenics-jit-runtime` owns backend selection, shared environment sanitization, Python/FFCx discovery, cache-root selection, diagnostics lifecycle, and MPI propagation. Each compiler package owns only compiler-specific payload and backend code beneath its own non-overlapping directory.

Until that split is implemented, Phase 1-3 TinyCC experiments may use a private prototype helper from the experiment tree, but `fenics-jit-tinycc` must not install a second copy of the production `Library/fenics-jit/runtime/fenics_jit_runtime.py` path already owned by LLVM-MinGW.

The existing DOLFINx Windows bootstrap is updated in Phase 4 to load the uniquely owned shared runtime component. TinyCC-only standalone operation must therefore not depend on the LLVM-MinGW package merely to obtain common runtime code.

## Architecture

TinyCC is not a drop-in executable replacement for `x86_64-w64-mingw32-clang` under setuptools' `mingw32` backend. The Windows port can emit DLLs directly with `tcc -shared`, but it uses its own compile/link model, object format, runtime, and Windows `.def` import definitions. Use an owned TinyCC compiler adapter plus the smallest required CFFI `build_ext` integration rather than pretending TinyCC is GCC/Clang.

```text
UFL
  -> FFCx generated C
  -> CFFI generated wrapper C
  -> shared Windows JIT runtime selector
  -> owned TinyCC build_ext/compiler adapter
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

1. **C language coverage** — current TinyCC development builds expose C11/gnu11 as their newest explicit language mode, while FFCx 0.11 requests C17. Prove the exact pinned TinyCC revision against the actual CFFI/FFCx generated-source corpus. Any actually required unsupported C17 semantics are a Phase 1 stop condition; do not broadly rewrite generated source.
2. **Windows ABI compatibility** — TCC-generated x86-64 PE code must interoperate with MSVC-built CPython/DOLFINx. Compare UFCx layout/calling-convention probes with the working LLVM-MinGW path. Preserve `__STDC_NO_COMPLEX__` unless a stronger ABI proof permits otherwise, and explicitly cover `long double` size/alignment and any representation crossing the compiler boundary.
3. **Python linking** — use a package-built `python3.def` targeting Stable-ABI `python3.dll`; explicitly suppress setuptools' native-Windows versioned `pythonXY` library selection and disable/verify absence of CPython header-driven library autolinking. CI must reject any versioned Python library request or PE import.
4. **CRT boundary** — current upstream TinyCC Win64 links `msvcrt.dll` by default, while the qualified LLVM-MinGW runtime is UCRT-based. Phase 1 must either establish a qualified UCRT-compatible TinyCC configuration or explicitly prove the mixed-CRT boundary safe for all generated wrapper/kernel interactions before packaging proceeds.
5. **PE hardening** — do not accept loadability alone. Inspect generated DLL characteristics and require the agreed Windows mitigation baseline (including ASLR/dynamic base and NX compatibility, plus high-entropy VA where applicable), relocations, and x64 unwind metadata. If the pinned TinyCC cannot emit an acceptable PE image without a small maintainable patch, reject it for shipping.
6. **Generated-code performance** — TinyCC should compile very quickly, but its generated code may be slower. Kernel/assembly execution must be benchmarked against LLVM-MinGW before any default switch.
7. **Setuptools/CFFI integration** — own compiler selection in-process; do not depend on global config or masquerade as the `mingw32` backend. Prefer an owned `build_ext` that directly instantiates the TinyCC compiler instead of relying on temporary registration through `new_compiler("tinycc")`, because imported compiler subclasses remain process-discoverable in modern setuptools. Treat CFFI's `_shimmed_dist_utils` and setuptools integration as a versioned boundary with explicit runtime dependencies and compatibility tests.
8. **Object/library incompatibility** — TinyCC's Windows object model is not interchangeable with normal MSVC/MinGW COFF objects/libraries. The adapter must explicitly reject foreign `.obj`/`.o`/`.lib`/archives and unsupported `extra_objects`/`cffi_libraries` rather than silently attempting to link them. Packaged `.def` imports and TCC-owned objects/archives are the explicit allowed path.
9. **Cache identity** — LLVM-MinGW and TinyCC artifacts must never share a physical FFCx/CFFI cache namespace. Backend-specific cache roots are mandatory and must be chosen before FFCx performs its cache lookup, not only inside the later CFFI compiler activation.
10. **Licensing** — TinyCC is LGPL-2.1; ship required notices/license material and satisfy source/modification distribution obligations before release.

## Upstream baseline

Do not assume the 2017 `0.9.27` Windows binary is the best baseline. The current TinyCC development branch has recent Win64/PE work. Phase 1 should pin an exact upstream development commit and checksum, while also recording whether the latest formal release passes the same proof. No moving branch/tag is acceptable in a reproducible package.

## Phases

| Phase | Spec | Outcome | Gate |
| --- | --- | --- | --- |
| 1 | [Compatibility proof](01-compatibility-proof.md) | Minimal CFFI + fresh FFCx Poisson JIT works with only TinyCC | Functional/ABI/security go-no-go |
| 2 | [Runtime package](02-runtime-package.md) | Reproducible backend-only `fenics-jit-tinycc` package | Package gate |
| 3 | [CFFI compiler adapter](03-cffi-adapter.md) | Owned TinyCC backend integrates hermetically with CFFI/setuptools | Integration gate |
| 4 | [Runtime integration](04-runtime-integration.md) | Single-owner shared runtime plus side-by-side backend selection | Isolation/ownership gate |
| 5 | [Functional validation](05-functional-validation.md) | Existing broad JIT matrix passes under TinyCC | Coverage gate |
| 6 | [Size and performance comparison](06-size-performance-comparison.md) | TinyCC tradeoffs measured against LLVM-MinGW | Decision gate |
| 7 | [Standalone and release decision](07-standalone-release-decision.md) | Standalone proof plus explicit fallback/default/no-ship decision | Release gate |

Phases are ordered. No runtime metadata/default switch may bypass an earlier gate.

## Primary gates

### Functional/ABI/security gate

Stop if the following cannot be made reliable with a small maintainable adapter and, if necessary, a narrowly scoped pinned TinyCC patch:

- minimal CFFI extension compiles/imports on standard GIL-enabled CPython 3.12-3.14;
- fresh FFCx Poisson JIT compiles, imports, assembles, and solves;
- no Visual Studio, host Windows SDK, GCC, Clang, or external linker participates;
- generated `.pyd` imports the intended `python3.dll` Stable ABI;
- no TinyCC link command requests `python312`, `python313`, `python314`, or another minor-version Python library, and no resulting PE imports a minor-version Python DLL;
- UFCx ABI probes, including `long double`/alignment coverage where relevant, match the MSVC/LLVM-MinGW consumer contract;
- the generated C corpus does not require unsupported compiler semantics;
- the CRT boundary is explicitly qualified, with current TinyCC's default `msvcrt.dll` use treated as a known issue rather than a hypothetical possibility;
- resulting PE modules satisfy the required Windows mitigation/unwind/relocation checks.

Python 3.15 preview qualification covers the standard GIL-enabled build only unless free-threaded Python is added later as a separate ABI/import-library qualification target.

### Size gate

Use the qualified LLVM-MinGW Stage AW package as the reference:

- installed content: **216.43 MiB**;
- compressed `.conda`: **51.34 MiB**.

TinyCC should be no more than **25% of the LLVM-MinGW installed footprint** (about 54 MiB) to justify proceeding past Phase 6. Record compressed size separately. A stretch objective is a single-digit-MiB dedicated runtime payload.

When side-by-side packaging is measured, distinguish the common `fenics-jit-runtime` bytes from backend-specific incremental bytes so TinyCC and LLVM-MinGW are compared fairly.

### Runtime performance gate

Measure both JIT latency and generated kernel/assembly performance.

- **default candidate:** representative assembly/runtime performance within 25% of LLVM-MinGW, with no numerical/stability regression;
- **fallback/compact candidate:** may be slower but should normally remain within 3x LLVM-MinGW on representative kernels while offering a compelling footprint reduction;
- **reject:** severe/highly variable slowdown, ABI/security instability, or compiler-specific failures make the size saving not worthwhile.

These thresholds guide the decision; inspect the benchmark distribution rather than only an average.

## CI policy

Use GitHub-hosted `windows-2022`. Add a dedicated **manual-only** workflow such as `.github/workflows/tinycc-jit.yml` until the experiment is proven. Keep `.github/workflows/stack.yml` as the only automatic PR/main workflow.

Because the runner contains Visual Studio and the Windows SDK, CI must sanitize the JIT process and prove non-use of host compiler/SDK inputs.

## Global acceptance criteria

The epic is successful when:

- an exact pinned TinyCC revision builds reproducibly;
- the package has no runtime dependency on an external compiler/linker;
- shared runtime ownership is single-source and compiler packages install to non-overlapping backend paths;
- `cffi` and `setuptools` are explicit runtime dependencies with a tested compatibility contract for the integration used by the adapter;
- CFFI/FFCx JIT works on supported CPython runtimes through an owned TinyCC adapter;
- generated modules use the intended Python Stable ABI, no minor-version Python link dependency is requested, and PE imports are audited;
- UFCx/Windows ABI compatibility, including the relevant floating-point/layout contract, is proven;
- the known TinyCC CRT model is qualified or replaced with a qualified UCRT-compatible configuration;
- generated PE modules meet the required Windows security/unwind/relocation baseline;
- unsupported foreign object/library inputs fail explicitly;
- the full existing FFCx functional matrix, backend-isolated cache behavior, paths-with-spaces, and MPI semantics pass;
- numerical results match the LLVM-MinGW reference;
- size and compile/runtime performance are measured side-by-side;
- a standalone bundle performs fresh JIT with the original prefix unavailable and without depending on LLVM-MinGW merely for shared runtime code;
- an explicit decision records whether TinyCC is a fallback, compact standalone backend, default backend, or rejected.

No automatic replacement of LLVM-MinGW is part of this plan.
