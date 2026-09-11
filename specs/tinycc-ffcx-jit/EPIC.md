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
- an owned TinyCC CFFI/build_ext adapter;
- backend metadata and diagnostics support.

This is a dedicated FFCx JIT backend, not a general-purpose conda compiler environment.

## Runtime ownership and package layout

Side-by-side backends must not own the same runtime-helper files.

However, do **not** restructure the qualified LLVM-MinGW production runtime merely to test whether TinyCC is viable. Phase 4 is split so the installed TinyCC package first passes a broad private qualification gate (Phase 4A). Only then may Phase 4B factor common Windows JIT selector/lifecycle code into one uniquely owned runtime component, provisionally:

```text
fenics-jit-runtime
  Library/fenics-jit/runtime/...

fenics-jit-llvm-mingw
  Library/fenics-jit/backends/llvm-mingw/...

fenics-jit-tinycc
  Library/fenics-jit/backends/tinycc/...
```

`fenics-jit-runtime` owns backend selection, shared environment sanitization, Python/FFCx discovery, cache-root selection, diagnostics lifecycle, activation serialization, and MPI propagation. It must have **no dependency on either compiler backend**. Each compiler package owns only compiler-specific payload and backend code beneath its own non-overlapping directory.

The default installation dependency shape is conceptually:

```text
fenics-dolfinx
  -> fenics-jit-runtime
  -> fenics-jit-llvm-mingw   # separate default-backend dependency, not a dependency of fenics-jit-runtime

fenics-jit-tinycc
  -> fenics-jit-runtime
```

Until the Phase-4B split is implemented, Phases 1-4A TinyCC work uses a private prototype/helper/activation path. `fenics-jit-tinycc` must not install a second copy of the production `Library/fenics-jit/runtime/fenics_jit_runtime.py` path already owned by LLVM-MinGW.

The existing DOLFINx Windows bootstrap is updated only in Phase 4B after Phase 4A passes. TinyCC-only standalone operation must ultimately depend on the common runtime owner, not on the LLVM-MinGW backend merely to obtain shared code.

## Architecture

TinyCC is not a drop-in executable replacement for `x86_64-w64-mingw32-clang` under setuptools' `mingw32` backend. The Windows port can emit DLLs directly with `tcc -shared`, but it uses its own compile/link model, ELF intermediate objects on the Windows `-c` path, runtime, and Windows `.def` import definitions.

The preferred production integration is therefore the narrowest CFFI-compatible path: an owned `build_ext` specialization whose `build_extension()` validates the CFFI `Extension` metadata and directly invokes TinyCC from generated C source to the final `.pyd`. Do not introduce a general-purpose distutils `CCompiler` implementation unless Phase 1/2 evidence shows CFFI actually requires one. This avoids exposing TinyCC ELF intermediates as a Windows object interchange surface.

CFFI's current `ffiplatform._build()` creates `_shimmed_dist_utils.Distribution` internally, calls `parse_config_files()`, then invokes `run_command("build_ext")`; callers cannot assume a normal setup.py `cmdclass` injection point. The plan therefore requires an exact owned interception. Prefer a temporary subclass replacement of `cffi._shimmed_dist_utils.Distribution` under the activation lock, with the subclass installing `TinyCCBuildExt` and suppressing external distutils/setuptools config. A narrow version-pinned `ffiplatform._build()` wrapper is the fallback only if the qualified CFFI version makes the Distribution interception unavailable.

```text
UFL
  -> FFCx generated C
  -> CFFI generated wrapper C
  -> owned CFFI Distribution interception
  -> private/shared Windows JIT lifecycle
  -> owned TinyCC build_ext adapter
  -> tcc -shared generated.c ... -o module.pyd
  -> DOLFINx
```

Keep both backends selectable only after Phase 4B integration:

```text
FENICS_JIT_COMPILER=llvm-mingw   # current reference/default
FENICS_JIT_COMPILER=tinycc       # experimental
```

Before Phase 4B, TinyCC qualification uses its private activation path and must not require changes to the production LLVM-MinGW selector/bootstrap.

## Backend cache identity

LLVM-MinGW and TinyCC artifacts must never share a physical FFCx/CFFI cache namespace, and successive incompatible builds of the same backend must not share one either.

The shared runtime must derive a stable immutable `backend-cache-id` before FFCx performs its first cache lookup. The identity must change whenever generated binary compatibility can change, including at least:

- compiler revision and local patch set;
- backend adapter/cache-schema version;
- owned CFFI interception/external-config-policy version;
- CRT model;
- ABI-affecting flags such as `-mms-bitfields`;
- language/optimization policy where it can affect generated compatibility;
- Python-link/import-definition policy;
- PE hardening/link configuration.

Use a physical namespace conceptually like:

```text
<cache>/ffcx/llvm-mingw/<backend-cache-id>/...
<cache>/ffcx/tinycc/<backend-cache-id>/...
```

Do not rely on the FFCx source/module hash to encode backend identity because FFCx performs cache lookup before the later CFFI/compiler activation path.

During private Phases 1-4A, TinyCC may use an explicitly private TinyCC-only cache root with the same immutable identity principles; full cross-backend isolation is established in Phase 4B.

## Main risks

1. **C language coverage** — current TinyCC development builds expose C11/gnu11 as their newest explicit language mode, while FFCx 0.11 requests C17. Prove the exact pinned TinyCC revision against the actual CFFI/FFCx generated-source corpus. Any actually required unsupported C17 semantics are a Phase 1 stop condition; do not broadly rewrite generated source.
2. **Windows ABI compatibility** — TCC-generated x86-64 PE code must interoperate with MSVC-built CPython/DOLFINx. TinyCC defaults to its non-MS/PCC bitfield layout unless `-mms-bitfields` is selected, so the Windows backend must either use `-mms-bitfields` or prove that no cross-compiler ABI structure contains bitfields. Current x86-64 TinyCC also uses a 16-byte/16-aligned `long double`, unlike the MSVC Windows model; any `long double` representation crossing the TinyCC/MSVC-UFCx boundary is therefore a Phase-1 stop condition unless an exact compatible representation is independently proven.
3. **Python linking** — use a package-built `python3.def` targeting Stable-ABI `python3.dll`; explicitly suppress setuptools' native-Windows versioned `pythonXY` library selection. CPython pragma autolinking is `_MSC_VER`-conditioned and `Py_NO_LINK_LIB` is only an additional defense where supported; command capture and final PE imports are authoritative. Record `_MSC_VER`, `Py_LIMITED_API`, and `Py_NO_LINK_LIB` behavior for each supported interpreter.
4. **CRT boundary** — current upstream TinyCC Win64 links `msvcrt.dll` by default, while the qualified LLVM-MinGW runtime is UCRT-based. Phase 1 must either establish a qualified UCRT-compatible TinyCC configuration or explicitly prove the mixed-CRT boundary safe for all generated wrapper/kernel interactions before production-adapter work proceeds.
5. **PE hardening/unwind** — the minimum x64 acceptance baseline is explicit: `DYNAMIC_BASE`, `HIGH_ENTROPY_VA`, and `NX_COMPAT` must be set; usable base relocation metadata must be present for ASLR; and x64 unwind/exception metadata for generated functions must satisfy the qualified Windows contract. Current TinyCC exposes PE linker controls for these mitigation bits even though x86-64 defaults may be zero. First qualify supported options and inspect the emitted image; use a narrowly scoped source patch only if supported options are insufficient.
6. **Generated-code performance** — TinyCC should compile very quickly, but its generated code may be slower. Kernel/assembly execution must be benchmarked against LLVM-MinGW before any default switch.
7. **Setuptools/CFFI interception** — own compiler selection in-process; do not depend on global config or masquerade as the `mingw32` backend. CFFI internally constructs and configures its `Distribution`, so the exact interception point is part of the supported compatibility contract. The owned path must suppress external `setup.cfg`, `pydistutils.cfg`, or equivalent compiler/linker influence and prove that with hostile-config tests.
8. **Process-global activation state** — current CFFI integration requires temporary process-global state such as environment variables and CFFI/setuptools hooks. Serialize activation with a process-wide reentrant lock, define nested activation semantics, and reject conflicting nested backend activation rather than permitting cross-thread/compiler state races.
9. **Object/library incompatibility** — TinyCC's Windows `-c` path emits ELF objects, not normal MSVC/MinGW COFF objects. The adapter must explicitly reject foreign `.obj`/`.o`/`.lib`/archives and unsupported `extra_objects`/`cffi_libraries`. Direct source-to-PYD compilation is preferred specifically to avoid depending on object interchange.
10. **System-library provenance** — native TinyCC can search the Windows system directory for DLLs. The backend must make this policy explicit: normal Windows system DLL resolution may be an approved operating-system input, but host SDK import libraries, arbitrary ambient library directories, and compiler-development inputs are not. Record resulting imports and approved search roots in diagnostics.
11. **Cache identity** — backend-specific physical roots and immutable backend-cache identities are mandatory and must be chosen before FFCx performs cache lookup.
12. **Premature production refactor** — TinyCC may fail broad generated-source/ABI/CRT/security qualification after a small proof succeeds. Phase 4A therefore runs broad private qualification before Phase 4B is allowed to change LLVM-MinGW runtime ownership/bootstrap/dependencies.
13. **Licensing** — TinyCC is LGPL-2.1; ship required notices/license material and satisfy source/modification distribution obligations before release.

## Upstream baseline

Do not assume the 2017 `0.9.27` Windows binary is the best baseline. The current TinyCC development branch has recent Win64/PE work. Phase 1 should pin an exact upstream development commit and checksum, while also recording whether the latest formal release passes the same proof. No moving branch/tag is acceptable in a reproducible package.

## LLVM-MinGW reference baseline

Use the immutable qualified Stage AW result merged through PR #9 as the comparison baseline:

- qualification run: stack #231 (`34580520920`);
- staged JIT payload: **215.19 MiB**;
- packaged installed content: **216.43 MiB**;
- compressed `.conda`: **51.34 MiB**.

Any future change of reference must name the exact replacement package/recipe identity and qualification run; do not silently compare TinyCC against a moving LLVM-MinGW branch state.

## Phases

| Phase | Spec | Outcome | Gate |
| --- | --- | --- | --- |
| 1 | [Compatibility proof](01-compatibility-proof.md) | Minimal CFFI + fresh FFCx Poisson JIT works with only TinyCC; exact CFFI interception/config isolation proven | Functional/ABI/security/hermeticity go-no-go |
| 2 | [CFFI compiler adapter](02-cffi-adapter.md) | Production TinyCC backend integrates hermetically with CFFI/setuptools through the owned Distribution/build_ext path | Integration/concurrency/config gate |
| 3 | [Runtime package](03-runtime-package.md) | Reproducible backend-only `fenics-jit-tinycc` package | Package/reproducibility + early footprint gate |
| 4A | [Private qualification](04-runtime-integration.md#phase-4a-private-tinycc-qualification-gate) | Installed TinyCC backend survives broad validation without production LLVM-MinGW runtime changes | Viability-before-refactor gate |
| 4B | [Runtime integration](04-runtime-integration.md#phase-4b-runtime-ownership-split) | Single-owner shared runtime plus side-by-side backend selection | Isolation/ownership/cache-identity gate |
| 5 | [Integrated functional validation](05-functional-validation.md) | Broad matrix passes again through shared runtime, including MPI/cross-backend/cache/concurrency tests | Integrated coverage gate |
| 6 | [Size and performance comparison](06-size-performance-comparison.md) | TinyCC tradeoffs measured against LLVM-MinGW | Final size/performance decision gate |
| 7 | [Standalone and release decision](07-standalone-release-decision.md) | Standalone proof plus explicit fallback/default/no-ship decision | Release gate |

Phases are ordered. Phase 1 may use a deliberately narrow prototype, but the production adapter is completed and qualified in Phase 2 before the reproducible package is finalized in Phase 3. Phase 4A must pass before any Phase-4B production runtime ownership/bootstrap/dependency refactor begins. No runtime metadata/default switch may bypass an earlier gate.

## Primary gates

### Functional/ABI/security/hermeticity gate

Stop if the following cannot be made reliable with a small maintainable adapter and, only when supported TinyCC options are insufficient, a narrowly scoped pinned TinyCC patch:

- minimal CFFI extension compiles/imports on standard GIL-enabled CPython 3.12-3.14;
- the exact CFFI `Distribution` interception path is proven for the supported CFFI/setuptools versions;
- external distutils/setuptools configuration cannot alter compiler selection, build directories, link inputs, or output placement;
- fresh FFCx Poisson JIT compiles, imports, assembles, and solves;
- no Visual Studio, host Windows SDK compiler inputs, GCC, Clang, or external linker participates;
- generated `.pyd` imports the intended `python3.dll` Stable ABI;
- no TinyCC link command requests `python312`, `python313`, `python314`, or another minor-version Python library, and no resulting PE imports a minor-version Python DLL;
- CPython preprocessor/link behavior (`_MSC_VER`, `Py_LIMITED_API`, `Py_NO_LINK_LIB`) is recorded, but command/import inspection remains authoritative;
- UFCx ABI probes, including packing/bitfield behavior, match the MSVC/LLVM-MinGW consumer contract;
- no `long double` representation crosses a compiler boundary unless exact compatibility has been independently demonstrated;
- `-mms-bitfields` is used by default for the Windows backend unless Phase 1 proves it unnecessary for every cross-compiler ABI surface;
- the generated C corpus does not require unsupported compiler semantics;
- the CRT boundary is explicitly qualified;
- generated x64 PE modules have `DYNAMIC_BASE`, `HIGH_ENTROPY_VA`, and `NX_COMPAT`, usable relocations, and the qualified x64 unwind/exception metadata;
- approved Windows system-DLL resolution is distinguished from forbidden host SDK/compiler-development inputs.

Python 3.15 preview qualification covers the standard GIL-enabled build only and is **informational/non-blocking** until Python 3.15 is promoted into the supported repository matrix. Free-threaded Python requires a separate ABI/import-library qualification target.

### Private viability-before-refactor gate

Phase 4A repeats a broad TinyCC-only functional/numerical/ABI/CRT/security/hermeticity matrix from the installed package while leaving the qualified LLVM-MinGW production runtime/bootstrap/dependency architecture unchanged. If this gate fails, stop the epic without performing the Phase-4B shared-runtime refactor.

### Early footprint gate

Phase 3 is allowed to fail early if the complete backend package is already too large to justify further integration work. The provisional early gate is the same <=25% installed-footprint threshold used for final qualification (about 54 MiB against Stage AW). Passing Phase 3 only means the footprint is promising enough to continue; it is **not** the final shipping decision.

### Final size/performance gate

Phase 6 repeats the installed/compressed/standalone footprint measurements after the complete integration and validation path exists and combines those measurements with JIT latency and generated-code performance.

- **default candidate:** representative assembly/runtime performance within 25% of LLVM-MinGW, with no numerical/stability regression;
- **fallback/compact candidate:** may be slower but should normally remain within 3x LLVM-MinGW on representative kernels while offering a compelling footprint reduction;
- **reject:** severe/highly variable slowdown, ABI/security instability, or compiler-specific failures make the size saving not worthwhile.

These thresholds guide the decision; inspect the benchmark distribution rather than only an average.

## CI policy

Use GitHub-hosted `windows-2022`. Add a dedicated **manual-only** workflow such as `.github/workflows/tinycc-jit.yml` until the experiment is proven. Keep `.github/workflows/stack.yml` as the only automatic PR/main workflow.

Because the runner contains Visual Studio and the Windows SDK, CI must sanitize the JIT process and prove non-use of host compiler/SDK development inputs. Normal Windows system DLLs may remain available only according to the explicitly qualified system-library policy.

The private Phase-4A workflow must not modify the production LLVM-MinGW bootstrap/dependency arrangement merely to run TinyCC. Phase-4B integration begins only after the Phase-4A decision is recorded.

## Global acceptance criteria

The epic is successful when:

- an exact pinned TinyCC revision builds reproducibly from a pinned bootstrap compiler/build chain, with a self-host stage or an explicitly documented equivalent reproducibility proof;
- the package has no runtime dependency on an external compiler/linker;
- the exact CFFI `Distribution` interception is qualified for the supported CFFI/setuptools range and hostile external config cannot affect compiler/linker selection;
- the packaged backend survives Phase 4A broad private qualification before production runtime ownership is changed;
- shared runtime ownership is single-source after Phase 4B, compiler packages install to non-overlapping backend paths, and the common runtime has no compiler-backend dependency;
- `cffi` and `setuptools` are explicit runtime dependencies with a tested compatibility contract for the integration used by the adapter;
- CFFI/FFCx JIT works on supported CPython runtimes through the narrow owned TinyCC `build_ext` path;
- temporary process-global activation state is protected by a reentrant process-wide lock and conflicting nested backend activation fails deterministically;
- generated modules use the intended Python Stable ABI, no minor-version Python link dependency is requested, and PE imports are audited;
- UFCx/Windows ABI compatibility, including packing/bitfield contracts, is proven and no incompatible `long double` value crosses the compiler boundary;
- the known TinyCC CRT model is qualified or replaced with a qualified UCRT-compatible configuration;
- generated PE modules meet the explicit x64 security/unwind/relocation baseline;
- approved Windows system-DLL resolution is explicit and ambient SDK/compiler-library resolution is excluded;
- unsupported foreign object/library inputs fail explicitly;
- each backend/cache-incompatible revision uses a distinct physical cache namespace selected before FFCx cache lookup;
- the full existing FFCx functional matrix, paths-with-spaces, thread-concurrency behavior, and MPI semantics pass after shared-runtime integration;
- numerical results match the LLVM-MinGW reference;
- size and compile/runtime performance are measured side-by-side against the pinned Stage AW baseline;
- a standalone bundle performs fresh JIT with the original prefix unavailable and without depending on LLVM-MinGW merely for shared runtime code;
- an explicit decision records whether TinyCC is a fallback, compact standalone backend, default backend, or rejected.

No automatic replacement of LLVM-MinGW is part of this plan.
