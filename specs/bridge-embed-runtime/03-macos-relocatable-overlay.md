# macOS relocatable embedded-runtime overlay qualification

**Status:** in-progress

## Goal

Turn the qualified macOS Zig/JIT producer inputs from phase 02 into exact,
relocatable arm64 and x86_64 FEniCS overlays with explicit ownership, native
closure, licenses, and deterministic artifact identities.

This phase owns **public producer qualification only**.  It does not claim a
specific private consumer runtime, GNU Octave or MATLAB bridge integration, and
does not publish a permanent release asset.  Consumer qualification belongs in
the consumer repository, where its own CI token can access its private history.

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
- Zig 0.15.2 archives and SHA-256 values already qualified by phase 02.

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
the producer prefix is explicitly enumerated in relocation evidence.  Final
runtime execution of those relocated files is a consumer-qualification gate.

The bootstrap's zero-argument `activate()` derives the runtime root from its own
installed location, prepends the private FEniCS site-packages path, configures
PETSc, and creates the Zig `cc` shim in a whitespace-safe temporary directory.
The latter is required because the qualified FFCx/distutils compiler command
cannot safely carry a compiler executable path containing spaces even though
the relocated runtime and JIT cache themselves must be tested under paths that
do contain spaces.

After both deterministic builds compare byte-for-byte, the workflow removes the
producer conda prefix/package cache and extracted Zig source tree.  No consumer
checkout or cross-repository credential is used from this public repository.
The generated compiler shim remains part of the overlay and explicitly supplies
consumer-runtime Python plus private FEniCS/PETSc include roots while discarding
ambient `-isysroot` / non-runtime `-isystem` inputs; its execution is verified by
the consumer repository.

## Consumer-qualification boundary

The intended bridge consumer repository is private while this producer is
public.  A repository-scoped `GITHUB_TOKEN` from this workflow cannot and must
not be widened with a private-repository credential merely to make producer CI
cross that boundary.  Therefore:

- this workflow proves exact SHA-256-anchored lock replay, installed-record
  identity, file ownership,
  licenses, relocation, Mach-O closure/signing, ZIP integrity and deterministic
  whole-file identity;
- it does **not** reconstruct or execute the private consumer runtime;
- consumer CI must reproduce the ZIP from the immutable producer revision and
  lock/Zig inputs, assert the same whole-file SHA-256, then perform its own
  overwrite, inherited-byte, activation, import, fresh-JIT and solve gates; and
- producer Actions artifacts remain finite-retention diagnostic transport, not
  durable release inputs.

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
- the bundled compiler shim retains the phase-02-qualified Zig targets
  `aarch64-macos.14.0` / `x86_64-macos.14.0` and Darwin dynamic-lookup form
  `-shared -Wl,-undefined,dynamic_lookup` for consumer JIT qualification.

Conda static `.a` archives are not shipped as runtime closure, avoiding an
unaudited class of Mach-O archive members.  The bundled Zig distribution is
retained as its exact upstream tree and the executed Zig binary is separately
identified by its whole-archive input hash and phase-02 hosted JIT evidence.

## Qualification sequence

1. replay the exact lock without solving and verify the installed package set;
2. package only explicit overlay ownership plus package/Zig license evidence;
3. relocate and audit the complete shipped Mach-O closure;
4. rebuild the same overlay a second time from the same installed lock and
   compare the ZIP, summary and checksum files byte-for-byte;
5. verify ZIP integrity, bootstrap syntax, bundled Zig presence and absence of
   producer-owned NumPy paths; and
6. upload the ZIP plus immutable manifest/native/license/hash evidence as
   finite-retention qualification diagnostics.

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
- [ ] Two independent packaging passes in the same clean hosted transaction
      produce byte-identical ZIP/summary/checksum outputs.
- [ ] Final arm64 and x86_64 ZIP names, whole-file SHA-256 values, manifest
      digests, native census, license inventory and hosted run evidence are
      recorded here after successful qualification.

Private-consumer activation/import/JIT/solve and inherited-runtime preservation
are deliberately **not** acceptance criteria of this public producer phase;
they gate the downstream consumer qualification against the frozen ZIP hashes.

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
