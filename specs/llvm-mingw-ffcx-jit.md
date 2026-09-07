# LLVM-MinGW runtime compiler for FFCx JIT on Windows

## Status

**Status:** proposed.

This specification covers the runtime compiler used by FFCx/CFFI on Windows. It does not change the compiler used to build PETSc, DOLFINx, Basix, or other native packages.

## Goal

Replace the current Visual Studio C compiler runtime dependency used for FFCx JIT with a small, self-contained LLVM-MinGW toolchain:

- Clang C compiler
- LLD linker
- mingw-w64/UCRT headers and import libraries
- x86-64 target only

The runtime package must work on supported Windows 10/11 systems without Visual Studio, Build Tools, MSYS2, or a developer command prompt.

After functional integration is complete, minimize the shipped toolchain by removing architectures, C++ support, tools, libraries, and symbols that are not needed for FFCx JIT.

TinyCC is a possible later fallback or size-optimization experiment, but is out of scope for this implementation.

## Background

The current `fenics-dolfinx` Windows runtime dependency includes the configured C compiler because FFCx uses CFFI to compile generated C code at runtime.

The actual DOLFINx and PETSc binaries should continue to be built with the existing VS2022 toolchain. FFCx JIT has much narrower requirements:

- compile generated C, not DOLFINx C++;
- include `ufcx.h` and standard C headers;
- compile the CFFI-generated wrapper against CPython headers;
- link a loadable `.pyd`;
- use the Windows/UCRT ABI compatible with the packaged CPython.

The runtime compiler therefore does not need the full Visual Studio build environment.

## Proposed architecture

Keep the existing native package build path unchanged:

```text
VS2022
  -> PETSc / DOLFINx / Basix / native package builds
```

Use LLVM-MinGW only for runtime JIT:

```text
UFL
  -> FFCx generated C
  -> CFFI / setuptools build_ext
  -> x86_64-w64-mingw32-clang
  -> LLD
  -> JIT .pyd
  -> DOLFINx
```

Ship the runtime compiler as a dedicated package, provisionally:

```text
fenics-jit-llvm-mingw
```

Do not expose or activate it as a general-purpose compiler environment unless required.

## Phase 1: prove LLVM-MinGW compatibility

Use the existing GitHub-hosted `windows-2022` runner as the primary implementation and test environment.

Start with an unmodified upstream LLVM-MinGW UCRT x86-64 distribution. GitHub's hosted Windows runner has Visual Studio installed, so the proof cannot establish that Visual Studio is physically absent from the machine. Instead, the JIT test must run in a deliberately sanitized process that makes MSVC tooling unavailable and proves from the actual commands that only the packaged LLVM-MinGW toolchain was used.

Before every fresh JIT test:

- do not enter a VS developer shell;
- replace `PATH` rather than inheriting the runner's compiler paths;
- remove Visual Studio activation variables such as `VSINSTALLDIR`, `VCINSTALLDIR`, `VCToolsInstallDir`, and all `VSCMD_*` variables;
- remove Windows SDK/compiler search variables including `INCLUDE`, `LIB`, `LIBPATH`, `WindowsSdkDir`, `WindowsSDKVersion`, `UniversalCRTSdkDir`, and `UCRTVersion`;
- ensure `cl.exe` and the MSVC `link.exe` are not resolvable from the JIT process;
- provide only the packaged LLVM-MinGW compiler/linker plus the FEniCS/Python runtime directories on `PATH`;
- do not provide an MSYS2 compiler fallback;
- clear the FFCx JIT cache.

A PowerShell test setup should be equivalent in intent to:

```powershell
$env:PATH = "$jitBin;$prefix;$prefix\Library\bin;$prefix\Scripts;$env:SystemRoot\System32;$env:SystemRoot"

$remove = @(
    "VSINSTALLDIR", "VCINSTALLDIR", "VCToolsInstallDir",
    "INCLUDE", "LIB", "LIBPATH",
    "WindowsSdkDir", "WindowsSDKVersion",
    "UniversalCRTSdkDir", "UCRTVersion"
)
$remove | ForEach-Object {
    Remove-Item "Env:$_" -ErrorAction Ignore
}
Get-ChildItem Env: |
    Where-Object Name -Like "VSCMD_*" |
    ForEach-Object { Remove-Item "Env:$($_.Name)" -ErrorAction Ignore }
```

The test must log the compiler and linker commands and fail if the JIT path invokes or discovers:

- `cl.exe`;
- MSVC `link.exe`;
- `vcvarsall.bat`;
- `vswhere.exe`;
- headers or libraries below a Visual Studio installation;
- headers or libraries below the host Windows Kits/SDK installation.

Use Clang's verbose/`-###` diagnostics and linker command tracing to record effective include and library search paths. The proof is not complete merely because `clang.exe` and LLD were the top-level executables: all compiler and linker inputs must resolve from the packaged LLVM-MinGW toolchain, the selected Python runtime, or normal system runtime locations.

This is stronger than relying on `where.exe` alone: the recorded JIT subprocess commands and effective search paths are the authoritative proof that neither MSVC nor the host Windows SDK participated in JIT.

The first acceptance test is the existing:

```text
scripts/test-poisson.py
```

This verifies generation, compilation, import of the JIT module, assembly, and solve.


### Compiler selection

CFFI delegates compilation to setuptools/distutils `build_ext`. On Windows this normally selects MSVC.

The direct `cffi.FFI.compile()` path used by FFCx does **not** expose a compiler-backend argument. Setting `CC` alone is insufficient: it changes the executable used by a GNU-style backend only after that backend has been selected. The implementation must therefore explicitly select setuptools' `mingw32` compiler backend as well as point that backend at LLVM-MinGW Clang.

The first prototype should use a JIT-local configuration owned by the FFCx cache/build directory, for example conceptually:

```ini
[build_ext]
compiler = mingw32
```

together with a process-local:

```text
CC = <runtime>/bin/x86_64-w64-mingw32-clang.exe
```

CFFI changes into its temporary build directory before creating the setuptools `Distribution`, whose `parse_config_files()` path is then used by `build_ext`. Verify this local-config mechanism against the exact CFFI/setuptools versions used by the packages rather than assuming it remains stable.

If a JIT-local `setup.cfg` cannot be made deterministic, use a small owned integration patch/helper that sets `build_ext.compiler = "mingw32"` programmatically before CFFI invokes the build. Do not rely on a user's global `setup.cfg`, shell activation, registry configuration, or command-line state.

Prefer the smallest maintainable integration in this order:

1. verified JIT-local setuptools compiler selection plus process-local `CC`;
2. a small FFCx/CFFI integration patch that sets the backend programmatically;
3. a narrow custom compile/link adapter if setuptools compiler selection proves too fragile.

Do not globally replace the Python build compiler.

The CI proof must record both:

- the selected setuptools compiler type, which must be `mingw32`;
- the actual compiler/linker subprocesses, which must resolve to the packaged LLVM-MinGW Clang/LLD toolchain.

This prevents a test from passing merely because `clang.exe` appears in logs while setuptools still initialized an unintended backend.

### FFCx compile flags

Current Windows FFCx assumes an MSVC-style compiler in places and may emit flags such as:

```text
-std:c17
```

GNU-driver Clang requires:

```text
-std=c17
```

Make compile flags depend on the selected compiler backend rather than only `sys.platform`.

Prefer an upstreamable FFCx fix if practical; otherwise carry a small documented package patch.


### CPython headers and Python import libraries

CFFI JIT compiles a real CPython extension. The JIT therefore needs both:

- the matching CPython development headers, including `Python.h` and `pyconfig.h`;
- a GNU/LLVM-MinGW-compatible Python import library.

In a normal conda environment the active Python package supplies its headers. A standalone/Nuitka bundle does not normally carry those development files, so they must be staged explicitly later in this plan.

CFFI already attempts to compile ordinary CPython 3 Windows extensions with `Py_LIMITED_API` by default when the interpreter configuration permits it. Therefore the main unresolved stable-ABI problem is not merely defining `Py_LIMITED_API`; it is ensuring that setuptools' MinGW link step binds the extension to the intended Python DLL.

On official Windows CPython, setuptools' `build_ext.get_libraries()` automatically adds a versioned Python library such as `python312`, `python313`, or `python314` whenever the selected compiler is non-MSVC. A `libpython3.a` file alone is therefore insufficient unless the integration also changes setuptools' selected library name.

Resolve the import-library strategy before switching runtime metadata:

1. **Preferred stable-ABI strategy:** retain CFFI's limited-API wrapper and ensure the link ultimately imports `python3.dll`. Two concrete implementations should be evaluated:
   - override the JIT-local setuptools Python-library selection so `build_ext` requests `python3`; or
   - provide version-named GNU import libraries such as `libpython312.a`, `libpython313.a`, and `libpython314.a` whose import descriptors deliberately target `python3.dll`. This lets setuptools keep requesting its normal versioned name while the produced PE module imports the stable-ABI DLL.
2. **Fallback:** if the stable-ABI route cannot be made reliable, generate a normal GNU import library for the active interpreter's versioned DLL and select it per CPython version. This is acceptable only if CI proves the resulting module on each supported interpreter and the package contents cannot silently bind to the build-time Python version.

Generate any required GNU import libraries during package construction and ship only the final import libraries required by JIT. Do not retain helper tools such as `llvm-dlltool` in the runtime solely for this purpose.

The CI proof must inspect the generated `.pyd` PE import table. If the stable-ABI strategy is selected, the acceptance condition is an import of `python3.dll`, not merely successful linking. Verify fresh JIT and module load on CPython 3.12, 3.13, and 3.14.

## Phase 2: dedicated runtime package

Add a package containing the LLVM-MinGW subset required by FFCx JIT.

Initial layout may follow:

```text
Library/
  fenics-jit/
    bin/
    lib/
    x86_64-w64-mingw32/
      include/
      lib/
    lib/clang/<version>/
```

Pin and record:

- LLVM-MinGW release;
- LLVM/Clang version;
- archive checksum;
- target: `x86_64-w64-mingw32`;
- CRT: UCRT.

The first package should contain a conservative working subset. Size minimization is a later phase and must not be mixed with the initial compatibility work.


## Phase 3: switch the DOLFINx runtime dependency

Keep Windows build requirements on VS2022 unchanged.

Replace the Windows runtime dependency that currently brings in the generic C compiler with the dedicated JIT package.

CFFI runtime compilation on Python 3.12+ requires setuptools' vendored distutils implementation. The conda-forge `cffi` runtime package does not itself guarantee a runtime `setuptools` dependency, so the FEniCS runtime must declare it explicitly rather than depending on an unrelated transitive install.

Conceptually:

```yaml
run:
  - fenics-jit-llvm-mingw
  - cffi
  - setuptools
  - fenics-ffcx
  - ...
```

Pin or constrain the CFFI/setuptools pair when necessary for the verified JIT adapter. Prefer keeping version-sensitive behavior behind the small owned adapter/helper so routine dependency updates can be tested in isolation.

The installed runtime must be able to perform FFCx JIT without conda compiler activation.


## Phase 4: JIT runtime setup

Provide a small runtime helper that owns all JIT build discovery rather than relying on ambient Python/compiler state. It must resolve paths relative to the installed prefix or bundled application and set only the environment/configuration required for the JIT subprocess.

At minimum the helper must provide or control:

- setuptools compiler backend: `mingw32`;
- LLVM-MinGW C compiler executable;
- Clang/LLD target and relevant compile/link flags;
- CPython include directory containing `Python.h` and `pyconfig.h`;
- directory and logical name of the GNU Python import library;
- FFCx/UFCx include directory;
- any packaged mingw-w64/UCRT include and import-library roots.

For a normal conda environment these paths may resolve into the active prefix. For a standalone/Nuitka bundle they must resolve into the staged bundle directories, including the staged `python-dev` tree. Merely copying CPython headers/import libraries beside the executable is insufficient: the helper must pass those paths into the CFFI/setuptools build so `build_ext` does not fall back to `sysconfig` locations in the original conda/build prefix.

The helper should not modify the user's persistent environment.

When verbose JIT logging is enabled, report the selected compiler, backend, target, CRT, Python include root, and Python link target so failures can be diagnosed, for example:

```text
FFCx JIT compiler: LLVM-MinGW / Clang <version> / mingw32 / x86_64 / UCRT
FFCx JIT Python: <include-root> / python3.dll
```

## Phase 5: functional test matrix

Run this matrix on the GitHub-hosted `windows-2022` runner under the sanitized JIT environment described above.

Before minimizing the toolchain, the full runtime compiler package must pass at least:

1. existing P1 Poisson solve;
2. P2 Poisson;
3. vector linear elasticity;
4. cell integrals;
5. exterior-facet integrals / Neumann terms;
6. coefficients and `Constant` values;
7. nonlinear residual and Jacobian forms;
8. `fem.Expression`;
9. JIT cache creation and reload;
10. two-rank MPI JIT, verifying rank-0 compilation and cache load on the other rank;
11. CPython 3.12, 3.13, and 3.14, matching the repository's current Windows channel test matrix;
12. install and cache paths containing spaces.

Generated JIT `.pyd` files should also be inspected for runtime dependencies. They must not require an installed LLVM-MinGW environment or unexpected compiler runtime DLLs.

For each fresh-cache test, retain the verbose compiler/linker log as a CI artifact so accidental fallback to MSVC is diagnosable even after a failure.

## Phase 6: minimize the toolchain


Before removing files, record a baseline for the runtime compiler footprint being replaced. The size report must include:

- installed size of the current Windows compiler dependency closure pulled into a `fenics-dolfinx` runtime environment;
- compressed package/download size attributable to that compiler closure where measurable;
- installed and compressed sizes of the conservative LLVM-MinGW JIT package;
- installed and compressed sizes after each minimization stage;
- incremental size added to the standalone/Nuitka bundle.

The minimum size acceptance criterion is that the final LLVM-MinGW JIT compiler footprint is **no more than 50% of the installed size of the current Windows runtime compiler dependency closure**, while still passing the complete functional matrix. If it does not meet that threshold, the implementation should not replace the current runtime dependency without an explicit decision explaining why the size reduction is still worthwhile.


Only start minimization after the conservative package passes the full test matrix.

Implement the reduction as a reproducible script, for example:

```text
scripts/minimize-jit-toolchain.ps1
```

The script must produce a manifest of retained files and record package size after each reduction stage.

Run every reduction stage directly on the GitHub-hosted Windows runner. Upload the size report, retained-file manifest, compiler/linker logs, and final minimized toolchain as workflow artifacts so each reduction can be inspected independently.

### A. Remove non-x86-64 targets

Remove all target-specific files for architectures not supported by this release, including as applicable:

- i686;
- ARMv7;
- AArch64;
- ARM64EC.

Retain only the x86-64 target.

Run the full JIT test matrix again.

### B. Remove C++ support

FFCx JIT generates C only.

Remove, where testing confirms they are unnecessary:

- libc++;
- libc++abi;
- C++ headers;
- C++ driver aliases;
- C++ target libraries;
- C++ exception/unwind support not required by the C runtime.

Retain any compiler-rt builtins needed by generated C.

Run the full JIT test matrix again.

### C. Remove unused LLVM tools

Use `clang -###` and observed JIT invocations to determine which executables are actually required.

Likely retained components are limited to:

- Clang driver/front-end;
- LLD component used by the driver;
- Clang resource headers;
- target C headers and import libraries;
- compiler-rt pieces proven necessary.

Candidates for removal include, when not required:

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

Do not remove a tool based only on name. Trace the compiler/linker commands and re-run tests after each group of removals.

### D. Minimize target libraries conservatively

Keep the C headers relatively conservative unless size measurements show they are significant.

Remove unused:

- C++ libraries;
- sanitizer runtimes;
- profiling runtimes;
- unsupported-architecture libraries;
- duplicate/static libraries that are not referenced by representative JIT links.

Be conservative with UCRT and mingw-w64 import libraries because future FFCx-generated code may use standard C library functionality not covered by a minimal Poisson test.

### E. Strip shipped binaries

Strip compiler/linker binaries during package construction where safe.

Do not ship the stripping tool in the final runtime package unless it is otherwise required.

Do not use executable compressors such as UPX.

### F. Reduction discipline

Each reduction stage must follow:

```text
working package
  -> remove one coherent file group
  -> record size
  -> run full JIT tests
  -> inspect JIT .pyd dependencies
  -> keep or revert the reduction
```

This should make the final minimized package reproducible and explainable rather than an undocumented hand-pruned toolchain.

## Phase 7: standalone/Nuitka staging

The existing standalone release process may still use VS2022 to build the Nuitka application itself. That is separate from the runtime FFCx compiler requirement.

Stage the minimized JIT compiler and all non-runtime Python development inputs required by CFFI into the standalone bundle explicitly.

At minimum this includes:

- the CPython headers matching the Python embedded in the bundle;
- the GNU/LLVM-MinGW-compatible Python import library selected by the strategy above;
- the setuptools/distutils implementation required by CFFI runtime compilation on Python 3.12+.

Ensure the Nuitka configuration explicitly includes dynamically imported build-backend modules such as setuptools instead of assuming static import discovery will retain them.

Build the Nuitka bundle using the existing Windows runner/build setup, then launch the produced standalone bundle in the same sanitized runtime environment used by the package-level JIT tests. Clear the bundled FFCx cache before launch so the standalone acceptance test must compile a fresh form with the staged LLVM-MinGW toolchain.

After the build, run the standalone acceptance test with the original conda/build prefix renamed, moved, or otherwise made inaccessible. This prevents accidental use of CPython headers, import libraries, setuptools modules, or compiler files that were not actually staged into the bundle.

Runtime discovery must be relative to the bundle and must not require:

- conda activation;
- Visual Studio;
- Windows SDK installation;
- registry discovery;
- `vcvarsall.bat`;
- `vswhere.exe`.

A final bundle should conceptually contain:

```text
application/
  <DOLFINx/PETSc/Python runtime>
  <FFCx/UFL/CFFI/setuptools runtime code>
  python-dev/
    <matching CPython headers>
    <selected GNU Python import library>
  jit/
    <clang>
    <lld>
    <mingw-w64/UCRT C headers>
    <mingw-w64/UCRT import libraries>
    <Clang resource files>
```

## CI requirements

Use GitHub-hosted `windows-2022` as the primary implementation and verification environment.

Initially add a dedicated workflow, for example:

```text
.github/workflows/llvm-mingw-jit.yml
```

Keep the experimental JIT work separate from the production `stack.yml` and `channel-dep-test.yml` workflows until the fresh Poisson JIT succeeds reliably. Once the runtime package is established, the relevant checks can be folded into the normal package/release gates.

The hosted runner contains Visual Studio and the Windows SDK, so CI must prove **non-use of both toolchains**, not physical absence from the machine. The JIT step must:

- run with a replaced/sanitized `PATH`;
- clear Visual Studio activation variables and inherited `INCLUDE`, `LIB`, `LIBPATH`, Windows SDK/UCRT variables, and `VSCMD_*`;
- explicitly select the packaged LLVM-MinGW Clang/MinGW backend;
- record the actual compiler and linker subprocess commands;
- record effective compiler include paths and linker library search/input paths;
- fail if `cl.exe`, MSVC `link.exe`, `vcvarsall.bat`, or `vswhere.exe` are used or discovered by the JIT path;
- fail if JIT compiler/linker inputs resolve below Visual Studio or host Windows Kits/SDK directories.

At minimum the CI gate must:

1. install or stage the pinned LLVM-MinGW UCRT x86-64 toolchain;
2. create the FEniCS/Python test environment;
3. prepare the matching CPython headers and selected GNU Python import library;
4. sanitize the JIT process environment, including compiler/SDK include and library variables;
5. clear the FFCx cache;
6. verify the selected compiler is the packaged LLVM-MinGW Clang;
7. record and validate Clang include paths plus linker search/input paths;
8. run `scripts/test-poisson.py` serially;
9. verify a fresh JIT module was created;
10. inspect the generated `.pyd` dynamic dependencies and Python DLL import;
11. retain compiler/linker/search-path logs as artifacts;
12. repeat the solve from the JIT cache;
13. run the two-rank MPI Poisson test with the same sanitized child environment;
14. run the broader form test matrix on CPython 3.12, 3.13, and 3.14;
15. run each staged toolchain-minimization pass, recording size and re-running the tests;
16. build the Nuitka standalone bundle with the required CPython development inputs and setuptools runtime code staged explicitly;
17. make the original build/conda prefix inaccessible and run a fresh standalone JIT under the same sanitized runtime environment.

The final release test should exercise the minimized package, not only the full upstream LLVM-MinGW archive.

## Acceptance criteria

The work is complete when:

- FFCx/CFFI JIT succeeds on the GitHub-hosted Windows runner with MSVC unavailable to the JIT process and compiler logs proving LLVM-MinGW/LLD were used;
- compiler and linker search-path diagnostics show no JIT headers or libraries coming from Visual Studio or the host Windows Kits/SDK installation;
- the runtime has no dependency on Visual Studio activation, the Windows SDK, MSYS2, `vcvarsall.bat`, or `vswhere.exe`;
- DOLFINx/PETSc continue to use the existing build toolchain;
- the existing Poisson solve and the broader JIT test matrix pass;
- MPI JIT and cache reuse work;
- the chosen Python import-library strategy is proven on CPython 3.12, 3.13, and 3.14;
- generated `.pyd` files load in the supported CPython runtimes;
- generated `.pyd` dependency inspection shows no unexpected compiler runtime dependency;
- the standalone/Nuitka bundle contains its matching CPython headers, required Python import library, and CFFI/setuptools build-backend runtime;
- the standalone/Nuitka bundle can perform a fresh JIT under the same sanitized environment with the original conda/build prefix inaccessible;
- the runtime compiler is packaged independently from the full development compiler stack;
- the minimized package is generated by a reproducible script;
- every retained toolchain component has a documented reason;
- package size before and after minimization is recorded in CI or release metadata;
- the final installed LLVM-MinGW JIT compiler footprint is no more than 50% of the current Windows runtime compiler dependency closure;
- the incremental standalone/Nuitka bundle size attributable to JIT support is recorded.

A one-time test on a genuinely pristine Windows VM with Visual Studio not installed is a useful final release-confidence check, but it is optional and is not a prerequisite for implementation or CI acceptance.


## Implementation order

1. Add a dedicated GitHub `windows-2022` experimental workflow for LLVM-MinGW JIT.
2. Download a pinned upstream LLVM-MinGW UCRT x86-64 archive and prove it can build and load a minimal CFFI extension with the packaged CPython.
3. Implement and verify deterministic JIT-local selection of setuptools' `mingw32` backend plus the packaged LLVM-MinGW `CC`; record the selected backend in CI.
4. Resolve FFCx compiler-specific flags, including using `-std=c17` for the GNU-driver Clang path before attempting the first FFCx Poisson JIT.
5. Resolve the CPython-header and Python import-library strategy, including setuptools' automatic versioned `pythonXY` library selection and whether version-named GNU import libraries can deliberately target `python3.dll`.
6. Add the sanitized JIT environment plus compiler/linker/search-path tracing; make accidental MSVC or host Windows SDK use a hard failure.
7. Run the existing FFCx/DOLFINx Poisson JIT from an empty cache with only LLVM-MinGW and the selected Python development inputs available to the JIT process.
8. Prove fresh JIT on CPython 3.12, 3.13, and 3.14 before changing runtime dependency metadata, including PE import-table inspection.
9. Add the dedicated runtime compiler package and an explicit runtime `setuptools` dependency.
10. Switch `fenics-dolfinx` Windows runtime metadata to the dedicated package.
11. Add the broader JIT, cache, dependency-inspection, and MPI test matrix.
12. Record the current compiler dependency-closure size and the conservative LLVM-MinGW package size.
13. Add deterministic toolchain minimization and run every reduction stage on the hosted runner.
14. Measure and remove unnecessary architectures, C++ support, tools, libraries, and symbols; require the final installed compiler footprint to be at most 50% of the current runtime compiler dependency closure.
15. Stage the minimized toolchain, matching CPython development inputs, and CFFI/setuptools build-backend runtime in the Nuitka standalone bundle.
16. Wire the standalone runtime helper to the staged Python headers/import libraries, make the original build prefix inaccessible, and force a fresh standalone JIT under the sanitized environment.
17. Fold the proven checks into the normal package/release CI gates.
18. Optionally perform a final one-time acceptance test on a Windows VM where Visual Studio is physically absent.

The primary functional go/no-go point is step 7: a fresh Poisson solve must JIT successfully with LLVM-MinGW while the JIT process cannot resolve or invoke MSVC tools and does not consume Visual Studio or host Windows SDK headers/libraries. Step 8 is the package-switch gate: all currently supported Windows CPython versions must pass before replacing the existing `c-compiler` runtime dependency. Step 14 is the size gate: the minimized compiler must meet the defined footprint reduction while still passing the full test matrix.
