# macOS relocatable embedded-runtime overlay qualification

**Status:** done

## Goal

Turn the qualified macOS Zig/JIT producer inputs from phase 02 into exact,
relocatable arm64 and x86_64 FEniCS overlays with explicit ownership, native
closure, licenses, and deterministic artifact identities.

This phase owns the complete **public producer contract**, including a
producer-local consumer qualification against a clean generic CPython 3.12 +
NumPy 2.5.2 host.  It does not claim GNU Octave, MATLAB, MEX, or any particular
downstream bridge integration, and it does not require access to another
repository.

## Immutable inputs

- producer base revision: `68eff23716dd5a3fd46347184b6c89356586e3ed`;
- producer package locks:
  - arm64 SHA-256
    `566b1f9fd653871bbac8ba535ff75719cce74a43acc7fcca2f114869a5dc0944`;
  - x86_64 SHA-256
    `34941247f237f6e36a564422860f27138e44dd6b0d20726e253aa2d5b2fb58a6`;
- the exact `micromamba list --explicit` URL-order evidence retained by the
  qualified prototype run is checked in as
  `locks/macos-arm64-explicit.txt` and `locks/macos-x86_64-explicit.txt`, with
  SHA-256 respectively
  `0dfcbf4405646de8a0b96470483ad1371e55e4538d2e6b27bfcfebcc96126547`
  and
  `af133bac1d322cc266e9781e36b920ffbe9afb8af7e462b015946d5f78b58c3f`;
- micromamba `2.10.0`, matching the successful prototype run;
- Zig 0.15.2 archives for the final overlays:
  - arm64 SHA-256
    `3cc2bab367e185cdfb27501c4b30b1b0653c28d9f73df8dc91488e66ece5fa6b`;
  - x86_64 SHA-256
    `375b6909fc1495d16fc2c7db9538f707456bfc3373b14ee83fdd3e22b3d43f7f`.
  The x86_64 overlay contains both exact upstream distributions: x86_64 for
  an architecture-matched fallback and arm64 as the compiler host when the
  consumer itself is translated by Rosetta. Phase 02 qualified the target/JIT
  design with Zig 0.15.2. A final-overlay experiment with 0.15.1 showed the
  translated x86_64 Zig/Clang failure persists (illegal instruction rather than
  the 0.15.2 SIGSEGV), so the producer keeps the already-qualified 0.15.2
  toolchain and removes Rosetta from the compiler process instead of changing
  the generated-code target.

The qualified explicit URL order is combined with the package-lock SHA-256
values to produce an `@EXPLICIT` replay transaction.  The URL set must match the
lock exactly and the retained explicit-file digest must match the prototype
evidence.  Release qualification must not supply a channel, matchspec, version
constraint, or other solver input while replaying that transaction.  The
`@EXPLICIT` URLs carry the checked-in SHA-256 values so micromamba verifies the
downloaded package bytes as part of replay; afterward the installed package
records, including the recorded SHA-256/MD5 identities, are compared
field-for-field with the checked-in lock before packaging starts.  The
micromamba cache is used only for extracted package metadata/license material;
qualification does not assume the action preserves downloaded `.conda`
archives after successful linking.

## Ownership and layout

The final overlay is additive. Its private conda-derived closure lives below
`fenics-runtime/conda/` and the target-architecture Zig distribution lives
below `fenics-runtime/zig/`. The x86_64 artifact additionally carries the exact
arm64 Zig distribution below `fenics-runtime/zig-native-arm64/` solely as a
compiler-host tool for Rosetta consumers. The only path intentionally added to
the consumer's Python framework is:

`Python.framework/Versions/3.12/lib/python3.12/site-packages/fenics_embed_runtime.py`

Producer CPython, NumPy, Tcl/Tk, host-application files, and producer
compiler/linker packages are not overlay-owned.  Package file ownership is derived from conda
`paths_data.paths` when present and falls back to the legacy `files` list only
when required.  Unsafe paths, package-owned content whose installed hash differs
from `sha256_in_prefix`, and cross-package path collisions fail closed.

Runtime-irrelevant build/developer metadata is also excluded rather than
shipping stale producer prefixes: static/libtool archives, pkg-config/CMake
metadata, PETSc build-conf/bin metadata, and generated Python bytecode are not
part of the embedded runtime contract.  Conda package test fixtures under
`etc/conda/test-files/` are likewise producer validation content, not shipped
runtime ownership.  The prefix-bound
`petsc4py/lib/petsc.cfg` is excluded; activation
supplies runtime-derived `PETSC_DIR` / `PETSC_ARCH` and a runtime-derived
`petsc4py.get_config()` instead.  Any remaining linked text file that contains
the producer prefix is explicitly enumerated in relocation evidence.  Final
runtime execution of those relocated files is a consumer-qualification gate.

The bootstrap's zero-argument `activate()` derives the runtime root from its own
installed location, prepends the private FEniCS site-packages path, configures
PETSc, and creates the Zig `cc` shim in a whitespace-safe temporary directory.
The latter is required because the qualified FFCx/distutils compiler command
cannot safely carry a compiler executable path containing spaces. The relocated
runtime itself is tested under a path containing spaces; the generated compiler
shim and transient JIT cache use whitespace-safe temporary paths outside
artifact ownership. Under Rosetta x86_64, activation detects
`sysctl.proc_translated`, selects the bundled arm64 Zig host, stages that exact
tree in the same whitespace-safe private temporary area, and launches it
explicitly with `/usr/bin/arch -arm64`. The compiler target remains
`x86_64-macos.14.0`, so the resulting JIT module is still x86_64 and loads into
the translated consumer process. The bundled x86_64 Zig tree remains available
as an architecture-matched fallback, but native Intel execution is outside this
hosted producer acceptance gate. The compiler shim also exposes the relocated
runtime through a whitespace-safe temporary symlink and rewrites only
runtime-owned include paths through that alias before invoking Zig; the real
runtime remains at the space-containing consumer path and all
provider/runtime-preservation checks use that real path. This does not
introduce an ambient compiler dependency or change runtime library ownership.

After both deterministic builds compare byte-for-byte, the workflow removes the
producer conda prefix/package cache and extracted Zig source tree.  No consumer
checkout or cross-repository credential is used from this public repository.
The generated compiler shim remains part of the overlay and explicitly supplies
consumer-runtime Python plus private FEniCS/PETSc include roots while discarding
ambient `-isysroot` / non-runtime `-isystem` inputs; its execution is verified by
the producer-local generic consumer runtime.

## Producer-local consumer qualification

The overlay must prove that it works for a conforming consumer without relying
on any downstream or private repository.  After deterministic packaging, CI deletes
the producer conda prefix, micromamba package cache, and extracted producer Zig
tree before constructing the consumer fixture.

The neutral consumer fixture is independently downloaded and hash-pinned:

- official CPython 3.12.10 universal2 macOS installer
  `python-3.12.10-macos11.pkg`, SHA-256
  `8373e58da4ea146b3eb1c1f9834f19a319440b6b679b06050b1f9ee3237aa8e4`;
- NumPy 2.5.2 CPython 3.12 macOS 14 wheel, selected by architecture:
  - arm64 SHA-256
    `6e8172ddfcf5cf74b811d372b570b83c60bd2de87a6fbfbebdadb4a9bd9c6cbb`;
  - x86_64 SHA-256
    `65f188481f1669e26f62b701e8205d19e460fa4a9b52a1414ba382330e4a3414`.

CI extracts the official `Python.framework` into a runtime path containing
spaces, executes the selected architecture slice (native arm64 or Rosetta
x86_64), installs only the pinned NumPy wheel, and snapshots every inherited
file/symlink before layering the overlay.  Overlay staging fails on any
consumer-owned file or symlink collision.

The staged runtime then runs with user Python state, Homebrew paths, compiler
commands, SDK discovery, and dynamic-library search paths poisoned.  It requires
idempotent activation, exact stack versions, consumer-owned NumPy, overlay-owned
FEniCS/PETSc/MPI providers, a fresh Zig/FFCx JIT, and the serial PETSc Poisson
solve with finite L2 error below 0.01.  Generated JIT Mach-O modules must match
the target architecture, target macOS 14.0, and contain no Homebrew,
`/usr/local`, Cellar, or user-home load paths.  Finally, every inherited
consumer file/symlink is rechecked byte-for-byte/mode-for-mode to prove the
overlay remained additive.

This is a producer acceptance test for the public CPython 3.12 overlay contract.
Downstream MATLAB/Octave/bridge qualification may add stricter integration
requirements, but it is not a prerequisite for this producer artifact.

## Relocation and native policy

- target minimum macOS version: 14.0;
- target architectures: native arm64 and Rosetta x86_64;
- all non-system Mach-O dependencies must resolve within the overlay;
- accepted external system roots are `/usr/lib/` and `/System/Library/`;
- producer-prefix, Homebrew, `/usr/local`, and user-home load paths/rpaths are
  forbidden;
- accepted private dependencies are rewritten to runtime-relative
  `@loader_path` references;
- all shipped Mach-O objects are ad-hoc signed after relocation and verified;
- runtime/loadable Mach-O objects must match the overlay target architecture;
  the x86_64 artifact's separately declared
  `fenics-runtime/zig-native-arm64/` compiler-host subtree is audited as arm64
  and is never part of the runtime/loadable dependency closure;
- the bundled compiler shim retains the phase-02-qualified Zig targets
  `aarch64-macos.14.0` / `x86_64-macos.14.0` and Darwin dynamic-lookup form
  `-shared -Wl,-undefined,dynamic_lookup` for consumer JIT qualification.

Conda static `.a` archives are not shipped as runtime closure, avoiding an
unaudited class of Mach-O archive members. The bundled Zig distributions are
copied from exact upstream archives bound to their official SHA-256 values;
their Mach-O executables are then ad-hoc signed with the rest of the shipped
closure, and the manifest binds those post-sign payload bytes. Consumer
evidence records the selected Zig source, executed binary, host architecture,
target architecture, and Rosetta translation state.

## Qualification sequence

1. replay the exact lock without solving and verify the installed package set;
2. package only explicit overlay ownership plus a complete package/Zig license
   inventory, retaining package-supplied license texts where present and
   binding split outputs without duplicated texts to a sibling output only when
   both carry byte-identical rendered recipe metadata;
3. relocate and audit the complete shipped Mach-O closure;
4. rebuild the same overlay a second time from the same installed lock and
   compare the ZIP, summary and checksum files byte-for-byte;
5. verify ZIP integrity, bootstrap syntax, bundled Zig presence and absence of
   producer-owned NumPy paths;
6. delete the producer source environments, construct the independent pinned
   CPython/NumPy consumer fixture, layer the overlay without overwrites, poison
   ambient discovery, activate twice, import the full stack, run a fresh
   Zig/FFCx JIT + PETSc Poisson solve, audit JIT Mach-O output, and recheck all
   inherited consumer bytes; and
7. upload the ZIP plus immutable manifest/native/license/hash and consumer
   execution evidence as finite-retention qualification diagnostics.

## Acceptance criteria

- [x] Both architecture locks replay through `@EXPLICIT` without dependency
      solving and produce an exact installed-record match.
- [x] Producer CPython, NumPy, Tcl/Tk, compiler/linker packages and consumer-owned
      runtime files are absent from the emitted overlay.
- [x] Every retained overlay file has unambiguous package/tool ownership and an
      integrity hash; every retained third-party package/tool has explicit
      license evidence and all package-supplied license texts/notices are
      retained, with split-output coverage mechanically bound to identical
      rendered recipe metadata rather than inferred from package names.
- [x] Complete shipped Mach-O closure passes declared-role architecture,
      minimum-OS, dependency, rpath, producer-path and ad-hoc-signature checks;
      the x86_64 runtime closure remains x86_64 while its isolated native
      compiler-host subtree is arm64.
- [x] Two independent packaging passes in the same clean hosted transaction
      produce byte-identical ZIP/summary/checksum outputs.
- [x] After producer source environments are removed, both architectures pass
      the independent CPython 3.12.10 + NumPy 2.5.2 consumer fixture with
      zero inherited-file overwrites, idempotent activation, exact provider
      ownership, fresh Zig/FFCx JIT, PETSc solve with L2 error < 0.01, JIT
      Mach-O audit, and inherited-runtime preservation.
- [x] Final arm64 and x86_64 ZIP names, whole-file SHA-256 values, manifest
      digests, native census, license inventory and hosted run evidence are
      recorded after successful qualification.

Bridge-specific MATLAB/Octave/MEX integration is deliberately outside this
producer phase; it can be qualified downstream without changing the public
overlay acceptance contract.

## Qualified hosted result

The canonical post-merge qualification ran from `main` revision
`7697af31337925e6033502c25d8d44b2d8b2bf85` in workflow run
`43219093728` and passed both matrix jobs:

| Target | Job | Overlay ZIP | Overlay SHA-256 | Poisson L2 error |
| --- | ---: | --- | --- | ---: |
| arm64 | `131185747839` | `fenics-embed-runtime-v0.1.0-macos-arm64-cp312.zip` | `f4314e94a39ae0ab14bab3afac1b929b0b9520a076cf290931ef6ed986428683` | `0.009053553714813364` |
| Rosetta x86_64 | `131185748201` | `fenics-embed-runtime-v0.1.0-macos-x64-cp312.zip` | `f16baa767766dc20fb51e9624d787f6ee2e7af2d3a8a5ccb5b551aa6b6f9b7ad` | `0.009053553714815176` |

The x86_64 consumer evidence records `rosetta_translated=true` while the
selected and executed Zig compiler host is arm64 from
`fenics-runtime/zig-native-arm64/`; generated and runtime/loadable artifacts
remain x86_64 and target macOS 14.0.

The finite-retention Actions evidence artifacts for that run are:

| Target | Artifact ID | Actions artifact digest |
| --- | ---: | --- |
| arm64 | `13945232041` | `sha256:daf58ab545b12b47c1d5ecf04b7c8dab16af934b3ce03a6dffae9c30c6e88201` |
| x86_64 | `13946436222` | `sha256:7a63e409d0a95995074212ae66e5fc33d40021c2d9d74435e5414456621e23ae` |

The repository's Actions retention policy reduced the requested 30-day
artifact retention to 3 days. These artifact IDs are diagnostic transport only;
the durable producer identity is the `main` revision, checked-in immutable
locks/toolchain hashes, workflow run/job identities, and whole-overlay hashes
recorded above.

The in-archive manifest enumerates every payload member except the manifest
itself, avoiding impossible self-hashing.  The adjacent producer summary binds
the manifest SHA-256 and whole ZIP SHA-256, and qualification independently
requires the ZIP path set to equal the manifest payload paths plus exactly
`fenics-embed-manifest.json`; unlisted ZIP members are rejected.
