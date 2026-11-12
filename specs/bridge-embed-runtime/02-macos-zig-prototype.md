# macOS Zig FFCx/JIT producer prototype

**Status:** done

The prototype workflow is retained for manual historical diagnostics only. Its
successful #27 transaction is frozen by the checked-in package locks; a fresh
conda solve can legitimately differ as conda-forge evolves. Current producer
acceptance therefore replays those immutable transactions in the relocatable
overlay workflow instead of requiring a fresh solve to reproduce them.

## Goal

Qualify one SDK-independent fresh-FFCx JIT direction for the bridge's future
macOS FEniCS overlays on both supported architectures before implementing the
relocatable overlay packager.

## Qualified producer identity

- repository: `precise-simulation/fenics-windows-ci`
- revision: `4d0c924c360a2bc2f7fd94d4fb6088ae6b45a6fb`
- pull request: #27
- workflow: `embedded-runtime-macos-prototype`
- successful run: `41293917357`
- runner: `macos-15`

The existing Windows `embedded-runtime` regression also passed for the same
producer revision, so the prototype did not regress the qualified Windows
overlay path.

## Immutable package locks

The successful run resolved 126 conda records per architecture. The exact
hash-complete records are retained in this repository:

| Architecture | Lock file | SHA-256 |
| --- | --- | --- |
| arm64 | `locks/macos-arm64-package-lock.json` | `566b1f9fd653871bbac8ba535ff75719cce74a43acc7fcca2f114869a5dc0944` |
| x86_64 | `locks/macos-x86_64-package-lock.json` | `34941247f237f6e36a564422860f27138e44dd6b0d20726e253aa2d5b2fb58a6` |

The corresponding explicit transaction text produced by micromamba had
SHA-256 `0dfcbf4405646de8a0b96470483ad1371e55e4538d2e6b27bfcfebcc96126547`
for arm64 and
`af133bac1d322cc266e9781e36b920ffbe9afb8af7e462b015946d5f78b58c3f`
for x86_64.

The common application-level closure selected by both transactions is:

- CPython 3.12.16;
- NumPy 2.5.2;
- DOLFINx 0.11.0;
- PETSc/petsc4py 3.25.6;
- mpi4py 4.1.2;
- MPICH 5.0.1;
- Basix 0.11.0;
- FFCx 0.11.0;
- UFL 2026.1.0.

The architecture-specific package filenames/builds/hashes are authoritative in
the checked-in lock JSON, not in this summary.

## Qualified JIT toolchain

The prototype used the official Zig 0.15.2 archive matching each architecture:

- arm64:
  `zig-aarch64-macos-0.15.2.tar.xz`,
  SHA-256
  `3cc2bab367e185cdfb27501c4b30b1b0653c28d9f73df8dc91488e66ece5fa6b`;
- x86_64:
  `zig-x86_64-macos-0.15.2.tar.xz`,
  SHA-256
  `375b6909fc1495d16fc2c7db9538f707456bfc3373b14ee83fdd3e22b3d43f7f`.

The wrapper targets `aarch64-macos.14.0` or `x86_64-macos.14.0`.
For Python/CFFI extension linking it translates the Apple
`-bundle -undefined dynamic_lookup` invocation to Zig's shared-library mode
while preserving Darwin dynamic lookup as
`-shared -Wl,-undefined,dynamic_lookup`.

Ambient compiler/SDK variables are removed and poisoned compiler launchers are
placed before the producer prefix. The successful JIT therefore does not rely
on `xcrun`, Xcode/Command Line Tools selection, Homebrew compiler paths, or an
ambient Apple SDK.

## Hosted result

Both jobs passed in run `41293917357`:

- arm64 job `124810664067`;
- Rosetta x86_64 job `124810664221`.

Each job:

1. created the selected FEniCS source environment;
2. retained the explicit transaction and hash-complete conda metadata lock;
3. verified the exact Zig archive hash;
4. imported the complete DOLFINx/PETSc stack;
5. compiled and loaded fresh FFCx CFFI extensions through Zig;
6. solved the serial PETSc Poisson fixture; and
7. verified every generated extension was the requested Mach-O architecture,
   required macOS 14.0, and linked only the Apple system runtime outside its
   generated module.

The numerical fixture reported:

- arm64 L2 error: `0.009053553714813364`;
- x86_64 L2 error: `0.009053553714815176`.

The retained Actions evidence artifacts are finite-retention transport only:

| Architecture | Artifact ID | Actions artifact digest |
| --- | ---: | --- |
| arm64 | `13077904852` | `sha256:dbda29fb5b1bf76022350c558d1a5d1677d865296f8985ec6123929a21acb719` |
| x86_64 | `13078696395` | `sha256:8884f02449afbf41d76802c1219e6b9a90dae688e91c2fab90bb52ebf5510d35` |

The checked-in lock files and producer revision are the durable transaction
identity; the Actions artifact IDs are diagnostic evidence, not release inputs.

## What this does not qualify

This prototype is not a bridge overlay release. It does not yet prove:

- replay of the exact locked packages without dependency solving;
- removal of producer-owned CPython and NumPy from the emitted overlay;
- layering onto an independent CPython 3.12.10 / NumPy 2.5.2 consumer runtime
  while preserving the consumer-owned NumPy payload;
- relocation of the full DOLFINx/PETSc/MPI/HDF5/native closure;
- final Mach-O load-command/rpath rewriting and signing;
- a complete third-party notice inventory; or
- final overlay ZIP identity/hash.

Those are the next embedded-runtime producer phase. Downstream bridge-specific
integration is separate from producer acceptance.
