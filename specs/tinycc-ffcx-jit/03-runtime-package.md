# Phase 3: package a reproducible TinyCC backend

**Status:** proposed.

## Objective

Package the Phase-2 production adapter and Phase-1-qualified TinyCC compiler as a reproducible, relocatable conda package provisionally named `fenics-jit-tinycc`.

The package must contain only the TinyCC compiler/backend payload and owned TinyCC integration support. It must not require a separate compiler package at runtime and must not claim ownership of the production shared runtime-helper path that is currently supplied by LLVM-MinGW.

The common selector/helper ownership split is completed in Phase 4. Until then, Phase-3 package tests may invoke a private TinyCC activation entry point directly.

## Package contents

Expected retained components beneath a backend-specific layout such as `Library/fenics-jit/backends/tinycc/`:

- `tcc.exe` for Windows x86-64;
- TinyCC's required runtime support such as `libtcc1.a` or equivalent for the pinned revision;
- minimal TinyCC standard/include tree required by the CFFI/FFCx generated source;
- minimal Windows import-definition files required by the compiler/runtime path;
- deterministic `python3.def` for Stable-ABI linking;
- the Phase-2 owned TinyCC direct `build_ext` adapter;
- backend metadata including the deterministic backend cache identity contribution;
- diagnostics support;
- TinyCC license/notices and source provenance metadata.

Do **not** install a competing copy of `Library/fenics-jit/runtime/fenics_jit_runtime.py` or another path intended to be owned by the eventual common runtime package.

Do not automatically ship:

- `libtcc.dll` unless the selected integration actually uses it;
- examples, documentation generators, tests, cross targets, 32-bit target support, ARM targets, debug tooling, or general development utilities;
- `tiny_impdef.exe` if all required `.def` files are generated at package-build time;
- a full Windows SDK or full mingw-w64 development environment.

## Runtime dependencies and compatibility

CFFI runtime compilation on Python 3.12+ uses CFFI's setuptools/distutils shim and setuptools' vendored distutils implementation. Declare both `cffi` and `setuptools` as explicit runtime dependencies of the TinyCC JIT integration rather than relying on them transitively.

The adapter uses version-sensitive integration points, so packaging must encode the Phase-2 compatibility contract:

- capture the exact `cffi` and `setuptools` versions used by the qualification;
- initially constrain the package to versions proven by CI if necessary;
- broaden any version range only after Phase-2 compatibility tests establish that the temporary `Distribution`, owned `build_ext`, activation lock, and CFFI compilation still behave as expected;
- fail clearly when an unsupported combination cannot resolve the TinyCC backend instead of falling back to another compiler.

## Build source and bootstrap reproducibility

Pin all compiler-production inputs, not only TinyCC source:

- exact upstream TinyCC commit or release;
- source archive/commit checksum;
- exact bootstrap compiler/toolchain identity and version used to build the first `tcc.exe`;
- bootstrap compiler package/archive provenance and checksum where available;
- build scripts/options/environment inputs that affect TinyCC output;
- package recipe inputs;
- any local compatibility/CRT/hardening patch hashes.

Do not describe the package as reproducible merely because the TinyCC source revision is fixed. The compiler that produces `tcc.exe` is part of the build input and must be captured.

### Preferred self-host procedure

Where practical:

1. build stage-0 TinyCC with the pinned bootstrap compiler;
2. build stage-1 TinyCC with stage-0;
3. rebuild stage-2 TinyCC with stage-1 using identical inputs;
4. compare stage-1/stage-2 binaries and required runtime artifacts after normalizing only documented nondeterministic fields;
5. package the qualified self-hosted stage according to the chosen reproducibility contract.

If TinyCC's supported Windows build flow prevents a clean two-stage self-host equivalence check, document the exact reason and use the strongest equivalent proof available. The acceptance record must still identify every compiler/build-chain input.

Build on `windows-2022`, but the produced runtime package must not depend on the host Visual Studio installation at end-user runtime. A pinned bootstrap compiler may be used at package-build time if it is explicitly part of the reproducibility record.

Rebuild the complete package twice in clean work directories. Compare:

- installed manifest paths and sizes;
- relevant file hashes;
- compiler/runtime binary hashes after any explicitly documented normalization;
- backend metadata recording source, bootstrap, patches, CRT policy, hardening policy, adapter version, and backend cache identity.

Where TinyCC's build embeds timestamps or other nondeterministic data, remove/normalize the source where reasonable or document the exact normalized fields and prove no semantic payload differs.

## Header strategy

Start from TinyCC's own Windows headers/support.

If official CPython headers or generated FFCx code require missing Windows definitions, add only the smallest coherent compatibility/header family needed by observed compilation. Do not import the complete host Windows SDK as a shortcut.

Every added header family must have a recorded reason and license provenance.

## Python definition file

Generate `python3.def` during package construction from a pinned/reference Stable-ABI export source or a validated `python3.dll` export set. The file must name `python3.dll` as the target library.

Do not require import-definition generation at end-user runtime. The packaged adapter must suppress implicit versioned `pythonXY` linkage and pass this definition explicitly.

Record `_MSC_VER`, `Py_LIMITED_API`, and `Py_NO_LINK_LIB` state for each supported Python version, but do not make package correctness depend on any one macro: captured link inputs and final PE imports remain authoritative.

## Windows ABI policy provenance

Package metadata and tests must encode the exact Phase-1/2 ABI policy:

- TinyCC language mode used for FFCx/CFFI sources;
- `__STDC_NO_COMPLEX__` policy;
- `-mms-bitfields` policy and the ABI evidence supporting it;
- packing/layout assumptions covered by the qualification probes;
- the known TinyCC x86-64 `long double` representation and proof that incompatible values do not cross the MSVC/UFCx boundary.

Do not allow a later TinyCC or adapter update to silently change these flags.

## CRT, system-library, and security provenance

The package recipe must encode the exact qualified runtime/link outcome:

- if TinyCC is patched/configured for a UCRT-compatible model, record and checksum that patch/configuration;
- if a mixed `msvcrt.dll` boundary is qualified, retain the corresponding runtime/ABI tests as package tests;
- record whether approved Windows system-DLL lookup or fully explicit packaged definitions are used;
- reject host SDK/MSVC/Python development library directories in installed-package tests;
- require `DYNAMIC_BASE`, `HIGH_ENTROPY_VA`, and `NX_COMPAT`, usable relocations, and qualified x64 unwind/exception metadata;
- if PE mitigation/unwind requires a TinyCC source patch after supported options were proven insufficient, ship that exact patch source/provenance and verify generated `.pyd` characteristics from the installed package.

Do not allow a later TinyCC upgrade to silently change CRT imports, system-library resolution, mitigation characteristics, or unwind/relocation behavior.

## Backend cache identity metadata

Package metadata must expose a deterministic backend cache identity contribution that changes whenever generated binary compatibility can change. Include at least:

- exact TinyCC source revision and local patch set;
- adapter/cache-schema version;
- CRT model;
- ABI-affecting compile flags including bitfield policy;
- Python-link/import-definition policy;
- PE hardening/link policy.

Phase 4 uses this identity to select the physical FFCx cache namespace before FFCx cache lookup.

## Relocatability

The package must work when installed into an arbitrary prefix, including paths containing spaces. All adapter/backend paths resolve relative to the installed backend root or explicit staged root; no build-prefix path may remain in runtime metadata.

## Licensing

TinyCC is LGPL-2.1. Package at minimum:

- exact license text;
- upstream source/commit URL and hash;
- bootstrap/build-chain provenance needed to reproduce the shipped TinyCC binary;
- list/hash of any local modifications;
- whatever source-availability material is required for binary redistribution.

Treat licensing completion as part of the package gate rather than release cleanup.

## Early footprint gate

Use the immutable LLVM-MinGW Stage AW baseline qualified in stack #231 (`34580520920`):

- 215.19 MiB staged;
- 216.43 MiB installed;
- 51.34 MiB compressed.

The complete TinyCC backend package should be <=25% of the LLVM-MinGW installed footprint (about 54 MiB) at this phase. This is an **early go/no-go gate** intended to avoid spending Phases 4-6 on a backend that has already lost its primary footprint advantage.

Passing this gate is not the final size/shipping decision. Phase 6 repeats the measurements after full integration/validation and combines them with JIT latency and generated-code runtime performance.

## Tasks

1. Add `recipes/fenics-jit-tinycc/` after Phase 2 succeeds.
2. Pin exact upstream source, bootstrap compiler/toolchain, build scripts/options, and package inputs.
3. Implement the preferred self-host/equivalent reproducibility procedure and document any normalized nondeterministic fields.
4. Stage the minimum x86-64 Windows backend payload under a non-overlapping TinyCC backend root.
5. Generate/package `python3.def` and required system `.def` files according to the qualified import policy.
6. Package the Phase-2 direct build_ext adapter and backend metadata without owning the common runtime-helper path.
7. Encode the qualified Windows ABI, CRT, system-library, fixed PE-hardening, and backend-cache-identity configuration from Phases 1-2.
8. Declare `cffi` and `setuptools` runtime dependencies and record the qualified versions/ranges.
9. Add package smoke tests that compile and import a minimal CFFI extension and verify no versioned Python link dependency.
10. Add package tests for foreign-object/library rejection, activation locking/restoration, bitfield/`long double` policy, PE mitigation, CRT imports, and system-library provenance.
11. Test install into a clean prefix and a path containing spaces.
12. Verify no runtime compiler input resolves to the build prefix or ambient Python/MSVC/Windows-SDK library directories.
13. Perform two clean package rebuilds and compare manifests/hashes under the documented reproducibility contract.
14. Record staged, installed, and compressed backend package sizes and apply the early footprint gate.

## Exit criteria

Phase 3 passes when the backend package installs into an otherwise compiler-free runtime prefix; performs the Phase-1 CFFI/Poisson proof through the Phase-2 direct build_ext adapter; declares and validates its CFFI/setuptools compatibility contract; preserves the qualified Windows ABI, known `long double` boundary, CRT, system-library, activation, fixed PE-security, and backend-cache-identity properties; is relocatable; can be reproduced from a pinned TinyCC source plus a pinned bootstrap/build chain under a documented binary/hash comparison procedure; contains complete licensing/provenance metadata; owns no common runtime-helper path; and passes the explicit early <=25%-of-Stage-AW installed-size gate.
