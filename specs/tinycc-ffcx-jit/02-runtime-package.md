# Phase 2: package a reproducible TinyCC backend

**Status:** proposed.

## Objective

Turn the Phase 1 proof into a reproducible, relocatable conda package provisionally named `fenics-jit-tinycc`.

The package must contain only the TinyCC compiler/backend payload and owned TinyCC integration support. It must not require a separate compiler package at runtime and must not claim ownership of the production shared runtime-helper path that is currently supplied by LLVM-MinGW.

The common selector/helper ownership split is completed in Phase 4. Until then, Phase 2 package tests may invoke a private TinyCC prototype activation entry point directly.

## Package contents

Expected retained components beneath a backend-specific layout such as `Library/fenics-jit/backends/tinycc/`:

- `tcc.exe` for Windows x86-64;
- TinyCC's required runtime support such as `libtcc1.a` or equivalent for the pinned revision;
- minimal TinyCC standard/include tree required by the CFFI/FFCx generated source;
- minimal Windows import-definition files required by the compiler/runtime path;
- deterministic `python3.def` for Stable-ABI linking;
- owned TinyCC compiler/build_ext adapter;
- backend metadata/diagnostics support;
- TinyCC license/notices and source provenance metadata.

Do **not** install a competing copy of `Library/fenics-jit/runtime/fenics_jit_runtime.py` or another path intended to be owned by the eventual common runtime package.

Do not automatically ship:

- `libtcc.dll` unless the selected integration actually uses it;
- examples, documentation generators, tests, cross targets, 32-bit target support, ARM targets, debug tooling, or general development utilities;
- `tiny_impdef.exe` if all required `.def` files are generated at package-build time;
- a full Windows SDK or full mingw-w64 development environment.

## Runtime dependencies and compatibility

CFFI runtime compilation on Python 3.12+ uses CFFI's setuptools/distutils shim and setuptools' vendored distutils implementation. Declare both `cffi` and `setuptools` as explicit runtime dependencies of the TinyCC JIT integration rather than relying on them transitively.

The adapter uses version-sensitive integration points, so packaging must also record a tested compatibility contract:

- capture the exact `cffi` and `setuptools` versions used by the Phase 1 proof;
- initially constrain the package to versions proven by CI if necessary;
- broaden any version range only after Phase 3 compatibility tests establish that the temporary `Distribution`, owned `build_ext`, and CFFI compilation still behave as expected;
- fail clearly when an unsupported combination cannot resolve the TinyCC backend instead of falling back to another compiler.

## Build source and reproducibility

Pin:

- exact upstream TinyCC commit or release;
- source archive/commit checksum;
- package recipe inputs;
- any local compatibility/hardening patch hashes.

Build on `windows-2022`, but the produced runtime package must not depend on the host Visual Studio installation.

Rebuild the package twice in clean work directories and compare the installed manifest. Where TinyCC's build embeds timestamps or non-deterministic data, either remove the source of non-determinism or document/normalize it explicitly.

## Header strategy

Start from TinyCC's own Windows headers/support.

If official CPython headers or generated FFCx code require missing Windows definitions, add only the smallest coherent compatibility/header family needed by observed compilation. Do not import the complete host Windows SDK as a shortcut.

Every added header family must have a recorded reason and license provenance.

## Python definition file

Generate `python3.def` during package construction from a pinned/reference Stable-ABI export source or a validated `python3.dll` export set. The file must name `python3.dll` as the target library.

Do not require import-definition generation at end-user runtime. The packaged adapter must suppress implicit versioned `pythonXY` linkage and pass this definition explicitly.

## CRT/security provenance

The package recipe must encode the exact CRT/PE-hardening outcome selected in Phase 1:

- if TinyCC is patched/configured for a UCRT-compatible model, record and checksum that patch/configuration;
- if a mixed `msvcrt.dll` boundary is qualified, retain the corresponding runtime/ABI tests as package tests;
- if PE mitigation flags require a TinyCC patch, ship that exact patch source/provenance and verify generated `.pyd` characteristics from the installed package.

Do not allow a later TinyCC upgrade to silently change CRT imports or mitigation characteristics.

## Relocatability

The package must work when installed into an arbitrary prefix, including paths containing spaces. All adapter/backend paths resolve relative to the installed backend root or explicit staged root; no build-prefix path may remain in runtime metadata.

## Licensing

TinyCC is LGPL-2.1. Package at minimum:

- exact license text;
- upstream source/commit URL and hash;
- list/hash of any local modifications;
- whatever source-availability material is required for binary redistribution.

Treat licensing completion as part of the package gate rather than release cleanup.

## Tasks

1. Add `recipes/fenics-jit-tinycc/` after Phase 1 succeeds.
2. Pin exact upstream source and build inputs.
3. Stage the minimum x86-64 Windows backend payload under a non-overlapping TinyCC backend root.
4. Generate/package `python3.def` and required system `.def` files.
5. Package the compiler/build_ext adapter and backend metadata without owning the common runtime-helper path.
6. Encode the qualified CRT and PE-hardening configuration/patches from Phase 1.
7. Declare `cffi` and `setuptools` runtime dependencies and record the qualified versions/ranges.
8. Add package smoke tests that compile and import a minimal CFFI extension and verify no versioned Python link dependency.
9. Add package tests for foreign-object/library rejection and PE mitigation/CRT imports.
10. Test install into a clean prefix and a path containing spaces.
11. Verify no compiler/runtime input resolves to the build prefix or ambient Python/MSVC library directories.
12. Perform two clean rebuilds and compare manifests/hashes.
13. Record staged, installed, and compressed backend package sizes.

## Exit criteria

Phase 2 passes when the backend package installs into an otherwise compiler-free runtime prefix, performs the Phase 1 CFFI/Poisson proof through its private Phase-2 activation path, declares and validates its CFFI/setuptools compatibility contract, preserves the qualified CRT/PE-security properties, is relocatable and reproducible, contains complete licensing/provenance metadata, owns no common runtime-helper path, and remains below the 25%-of-LLVM-MinGW installed-size gate.
