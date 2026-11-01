# macOS relocatable embedded-runtime overlay qualification

**Status:** in-progress

## Goal

Turn the qualified macOS Zig/JIT producer inputs from phase 02 into exact,
relocatable arm64 and x86_64 FEniCS overlays that can be layered on the bridge's
already-qualified macOS NumPy runtime without replacing any bridge-owned byte.

This phase owns producer qualification only.  It does not claim GNU Octave or
MATLAB bridge integration and does not publish a permanent release asset.

## Immutable inputs

- producer base revision: `68eff23716dd5a3fd46347184b6c89356586e3ed`;
- bridge Phase-03 qualification revision:
  `cf5fecea11bd1c727d8ff2d9fc5ea1b74d323d8d`;
- CPython consumer runtime: 3.12.10 from the exact `actions/python-versions`
  release inputs retained by the bridge;
- NumPy consumer runtime: 2.5.2 from the exact architecture-specific wheels
  retained by the bridge Phase-03 contract;
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
- Zig 0.15.2 archives and SHA-256 values already qualified by phase 02.

The qualified explicit URL order is combined with the package-lock SHA-256
values to produce an `@EXPLICIT` replay transaction.  The URL set must match the
lock exactly and the retained explicit-file digest must match the prototype
evidence.  Release qualification must not supply a channel, matchspec, version
constraint, or other solver input while replaying that transaction.  After
installation, every cached package archive is independently hashed against the
lock and the installed package records are compared field-for-field with the
checked-in lock before packaging starts.

## Ownership and layout

The final overlay is additive.  Its private conda-derived closure lives below
`fenics-runtime/conda/`, the exact Zig distribution lives below
`fenics-runtime/zig/`, and the only path intentionally added to the bridge's
Python framework is:

`Python.framework/Versions/3.12/lib/python3.12/site-packages/fenics_embed_runtime.py`

Producer CPython, NumPy, Tcl/Tk, bridge MEX, and producer compiler/linker
packages are not overlay-owned.  Package file ownership is derived from conda
`paths_data.paths` when present and falls back to the legacy `files` list only
when required.  Unsafe paths, package-owned content whose installed hash differs
from `sha256_in_prefix`, and cross-package path collisions fail closed.

Runtime-irrelevant build/developer metadata is also excluded rather than
shipping stale producer prefixes: static/libtool archives, pkg-config/CMake
metadata, and PETSc build-conf/bin metadata are not part of the embedded runtime
contract.  The prefix-bound `petsc4py/lib/petsc.cfg` is excluded; activation
supplies runtime-derived `PETSC_DIR` / `PETSC_ARCH` and a runtime-derived
`petsc4py.get_config()` instead.  Any remaining linked text file that contains
the producer prefix is explicitly enumerated in relocation evidence and must
survive the hosted import/JIT/solve qualification after relocation.

The bootstrap's zero-argument `activate()` derives the runtime root from its own
installed location, prepends the private FEniCS site-packages path, configures
PETSc, and creates the Zig `cc` shim in a whitespace-safe temporary directory.
The latter is required because the qualified FFCx/distutils compiler command
cannot safely carry a compiler executable path containing spaces even though
the relocated runtime and JIT cache themselves must be tested under paths that
do contain spaces.

Before consumer qualification starts, the workflow deletes the producer conda
prefix/package cache, extracted producer Zig tree, and the CPython toolcache used
to reconstruct Phase 03.  The generated compiler shim explicitly supplies the
staged CPython and private FEniCS/PETSc include roots and discards ambient
`-isysroot` / non-runtime `-isystem` inputs.  This turns an accidental absolute
producer/compiler path into a hard failure instead of allowing the producer
source environments to mask a relocation bug.

## Exact bridge inheritance gates

The producer workflow reconstructs the Phase-03 runtime at the exact qualified
bridge revision and fails if its previously retained identities drift.  The
current required identities are:

| Identity | arm64 | x86_64 |
| --- | --- | --- |
| MEX SHA-256 | `23f172fb23db8cd599891246683a72ef343ac8717799a2c7a661c3f7babbc60e` | `188bc10b098e96ceb7791acd68953375d026fb0fa476fb079e0032b76d2bc50c` |
| Staged CPython framework SHA-256 | `3b8548572d49de187aad18b0a176b6a5d204b64da623942e681e97ce85a525e0` | `3b8548572d49de187aad18b0a176b6a5d204b64da623942e681e97ce85a525e0` |
| Staged CPython executable SHA-256 | `564913c68be0bcbd38867413ea778df0290d25a443225ba1a66c3b62dc5daf50` | `564913c68be0bcbd38867413ea778df0290d25a443225ba1a66c3b62dc5daf50` |
| Core shared-map SHA-256 | `8fbb6dffb90498c7099ab1e9e1f0db697a5c5814f178c8a860e1661b1d2383df` | `575cacd0081f3d303c041c8ae1862c095b8fd52cd519be1a7ce75a467f04a370` |
| NumPy 923-file payload-map SHA-256 | `d7a840c84cd5d4219478d931a683ef924f265d68c2d0a6e6f49a2fa0c3f41445` | `b35e3f59780f77e7130b2f2a73fcaac6480230d2ef0af06b75d19fbe26aa3ca6` |
| NumPy payload-manifest SHA-256 | `957e7dfb1e4a246ada9f2f9713ebf980de0301fa24476e8f48a92cface7347a0` | `45ceeeadb54e43969b74059bc1bba5dafe37a49b2334fb29f275257f99533801` |
| NumPy native-census SHA-256 | `a4061c9932031270feeaa00bc986dcb8288c4e0ae740cc70cd1f0dc73ec45860` | `2edb07f2902aa79d2654ffbfb1342b302d59ff0b56c04aa6e520249face20570` |

The Phase-03 evidence also retained whole-file provenance hashes
`cfe6d574...` / `481bf49d...` for core and `cb589f66...` / `e13f92e1...`
for NumPy. Those JSON files include absolute `selected_prefix` and
`selected_executable` values from the original runner and are therefore
path-sensitive historical evidence, not byte-reproduction gates. The producer
instead verifies their stable provenance fields plus the runtime byte-map
identities above.

Before overlay extraction, the qualification harness snapshots every inherited
file and symlink.  Overlay extraction rejects every pre-existing destination.
The full inherited snapshot and the complete Phase-03 NumPy payload manifest
are verified again after extraction and after the JIT/PETSc test.

The bridge's original Phase-03 hosted jobs used the floating `macos-15` runner
label.  This producer therefore records the concrete Actions image version,
Xcode, Clang, SDK and host OS used for every reconstruction run but does not
permit those observations to redefine Phase-03.  If a later runner-image change
causes the frozen MEX/core/NumPy identities above to drift, overlay qualification
fails closed and Phase-03 must be requalified explicitly rather than accepting
new bytes here.

There is also an inherited compatibility-floor discrepancy that this producer
must not conceal.  The qualified native-arm64 Phase-03 run `41278807666`
records the frozen `bridge.mex` as the core maximum-minimum-OS object with
`minos 15.0`, because that job built the MEX with the runner-default deployment
target.  The qualified x86_64 Phase-03 MEX is explicitly 14.0.  This producer
continues to require every **new overlay/JIT Mach-O** to be no newer than 14.0
and preserves the exact Phase-03 MEX bytes; therefore it cannot by itself claim
that the combined arm64 bridge runtime supports macOS 14.  The bridge Phase-04
handoff must keep that issue open until the inherited arm64 core runtime is
requalified at the intended floor or the release floor is explicitly revised.

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
- fresh FFCx extensions are built through Zig targets
  `aarch64-macos.14.0` / `x86_64-macos.14.0`, preserving Darwin dynamic lookup
  as `-shared -Wl,-undefined,dynamic_lookup`.

Conda static `.a` archives are not shipped as runtime closure, avoiding an
unaudited class of Mach-O archive members.  The bundled Zig distribution is
retained as its exact upstream tree and the executed Zig binary is separately
identified by its whole-archive input hash and hosted JIT evidence.

## Qualification sequence

1. replay the exact lock without solving and verify the installed package set;
2. package only explicit overlay ownership plus package/Zig license evidence;
3. relocate and audit the complete shipped Mach-O closure;
4. reconstruct the exact bridge Phase-03 runtime and verify its retained
   identities;
5. copy it to a path containing spaces and layer the overlay without overwrites;
6. poison ambient Python, Homebrew, compiler, SDK and native-library state;
7. call `fenics_embed_runtime.activate()` twice and import the complete stack;
8. require bridge-owned NumPy and private-overlay DOLFINx/PETSc ownership;
9. perform a fresh FFCx JIT and serial PETSc Poisson solve; and
10. reverify every inherited Phase-03 byte after execution.

## Acceptance criteria

- [ ] Both architecture locks replay through `@EXPLICIT` without dependency
      solving and produce an exact installed-record match.
- [ ] Producer CPython, NumPy, Tcl/Tk, compiler/linker packages and bridge-owned
      runtime files are absent from the emitted overlay.
- [ ] Every retained overlay file has unambiguous package/tool ownership and an
      integrity hash; every retained third-party package/tool has license
      evidence.
- [ ] Complete shipped Mach-O closure passes architecture, minimum-OS,
      dependency, rpath, producer-path and ad-hoc-signature checks.
- [ ] Exact Phase-03 MEX/core/NumPy identities are reproduced and remain
      byte-identical before and after overlay qualification.
- [ ] Zero-argument/idempotent activation succeeds from a runtime path with
      spaces while the Zig compiler shim remains whitespace-safe.
- [ ] Full imports, fresh Zig FFCx JIT and serial PETSc Poisson solve pass with
      ambient compiler/SDK/Homebrew/Python/native discovery poisoned.
- [ ] Final arm64 and x86_64 ZIP names, whole-file SHA-256 values, manifest
      digests, native census, license inventory and hosted run evidence are
      recorded here after successful qualification.

## Planned artifact identities

- `fenics-embed-runtime-v0.1.0-macos-arm64-cp312.zip`
- `fenics-embed-runtime-v0.1.0-macos-x64-cp312.zip`

The filenames are fixed for qualification; their whole-file SHA-256 values are
not known until the hosted producer run passes and remain intentionally unset.

The in-archive manifest enumerates every payload member except the manifest
itself, avoiding impossible self-hashing.  The adjacent producer summary binds
the manifest SHA-256 and whole ZIP SHA-256, and qualification independently
requires the ZIP path set to equal the manifest payload paths plus exactly
`fenics-embed-manifest.json`; unlisted ZIP members are rejected.
