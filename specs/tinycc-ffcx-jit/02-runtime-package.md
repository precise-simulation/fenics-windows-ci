# Phase 2: package a reproducible TinyCC runtime

**Status:** proposed.

## Objective

Turn the Phase 1 proof into a reproducible, relocatable conda package provisionally named `fenics-jit-tinycc`.

The package must contain only the TinyCC runtime compiler payload and owned JIT integration support. It must not require a separate compiler package at runtime.

## Package contents

Expected retained components:

- `tcc.exe` for Windows x86-64;
- TinyCC's required runtime support such as `libtcc1.a` or equivalent for the pinned revision;
- minimal TinyCC standard/include tree required by the CFFI/FFCx generated source;
- minimal Windows import-definition files required by the compiler/runtime path;
- deterministic `python3.def` for Stable-ABI linking;
- owned TinyCC compiler/build_ext adapter;
- runtime helper/backend metadata;
- TinyCC license/notices and source provenance metadata.

Do not automatically ship:

- `libtcc.dll` unless the selected integration actually uses it;
- examples, documentation generators, tests, cross targets, 32-bit target support, ARM targets, debug tooling, or general development utilities;
- `tiny_impdef.exe` if all required `.def` files are generated at package-build time;
- a full Windows SDK or full mingw-w64 development environment.

## Runtime dependencies and compatibility

CFFI runtime compilation on Python 3.12+ uses CFFI's setuptools/distutils shim and setuptools' vendored distutils implementation. Declare both `cffi` and `setuptools` as explicit runtime dependencies of the TinyCC JIT integration rather than relying on them transitively.

The adapter uses private/version-sensitive integration points, so packaging must also record a tested compatibility contract:

- capture the exact `cffi` and `setuptools` versions used by the Phase 1 proof;
- initially constrain the package to versions proven by CI if necessary;
- broaden any version range only after Phase 3 compatibility tests establish that compiler discovery, the temporary `Distribution`, custom `build_ext`, and CFFI compilation still behave as expected;
- fail clearly when an unsupported combination cannot resolve the TinyCC backend instead of falling back to another compiler.

## Build source and reproducibility

Pin:

- exact upstream TinyCC commit or release;
- source archive/commit checksum;
- package recipe inputs;
- any local compatibility patch hashes.

Build on `windows-2022`, but the produced runtime package must not depend on the host Visual Studio installation.

Rebuild the package twice in clean work directories and compare the installed manifest. Where TinyCC's build embeds timestamps or non-deterministic data, either remove the source of non-determinism or document/normalize it explicitly.

## Header strategy

Start from TinyCC's own Windows headers/support.

If official CPython headers or generated FFCx code require missing Windows definitions, add only the smallest coherent compatibility/header family needed by observed compilation. Do not import the complete host Windows SDK as a shortcut.

Every added header family must have a recorded reason and license provenance.

## Python definition file

Generate `python3.def` during package construction from a pinned/reference Stable-ABI export source or a validated `python3.dll` export set. The file must name `python3.dll` as the target library.

Do not require import-definition generation at end-user runtime. The packaged adapter must suppress implicit versioned `pythonXY` linkage and pass this definition explicitly.

## Relocatability

The package must work when installed into an arbitrary prefix, including paths containing spaces. All adapter/helper paths resolve relative to the installed package root or explicit staged root; no build-prefix path may remain in runtime metadata.

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
3. Stage the minimum x86-64 Windows runtime payload.
4. Generate/package `python3.def` and required system `.def` files.
5. Package the compiler/build_ext adapter and runtime helper.
6. Declare `cffi` and `setuptools` runtime dependencies and record the qualified versions/ranges.
7. Add package smoke tests that compile and import a minimal CFFI extension and verify no versioned Python link dependency.
8. Test install into a clean prefix and a path containing spaces.
9. Verify no compiler/runtime input resolves to the build prefix or ambient Python/MSVC library directories.
10. Perform two clean rebuilds and compare manifests/hashes.
11. Record staged, installed, and compressed package sizes.

## Exit criteria

Phase 2 passes when the package installs into an otherwise compiler-free runtime prefix, performs the Phase 1 CFFI/Poisson proof, declares and validates its CFFI/setuptools runtime integration contract, is relocatable and reproducible, contains complete licensing/provenance metadata, and remains below the 25%-of-LLVM-MinGW installed-size gate.
