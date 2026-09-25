# Phase 0 reference identity and baseline decomposition

**Status:** implemented; immutable identity recovered from the qualified Stage-AW run and upstream release sources.

## Immutable reference

The control remains Stage AW from stack #231, run `34580520920`, repository head
`1d970c7372c673b086ce75210b865768b2b18e42`.

The retained workflow artifact identified package
`fenics-jit-llvm-mingw-20260826-h9490d1a_49.conda` with SHA-256
`c7be1959bf489cdeaf2e968b2fcbc092db3b65acd9ba242c5fd9cd47489932bc`
and compressed size 53,830,154 bytes.

The immutable source identities are:

- llvm-mingw tag `20260826`, commit `14614551fb5fc0f725933e4959c75c06d347acfa`;
- LLVM/Clang/LLD `llvmorg-23.1.0`, commit `ea7d852a70e8bdfaf601d6626a760f9771b2c4b4`;
- compiler-rt from that same LLVM monorepo commit;
- mingw-w64 commit `a3d708261d5ba659205067cb82cae36e7ae8bbb0`;
- immutable upstream x86-64 UCRT archive SHA-256
  `ae601f4e0f72bbdf441ad2df8bb16f037e2e9251559ea6b37b4057aef39c06c3`.

These values are machine-readable in `scripts/micro-clang-jit/reference.json` and are
validated before Phase 1 is allowed to build.

## Driver/ABI control

The upstream release machinery establishes the reference GNU/MinGW driver policy:

- target `x86_64-w64-mingw32`;
- UCRT, default `_WIN32_WINNT=0x601`;
- compiler-rt builtins;
- libunwind;
- LLD through the GNU/MinGW `ld.lld` path.

Phase 1 additionally captures `-###` driver output from both the immutable binary
reference and the source-built candidate and compares target triple, target CPU,
target features, `long double` layout, and an MS-bitfield layout probe.

## Stage-AW retained payload

The retained Stage-AW size report totals 225,940,525 bytes (215.474 MiB):

| Category | Bytes | MiB |
| --- | ---: | ---: |
| shared compiler runtime DLLs | 129,769,984 | 123.758 |
| root mingw-w64/UCRT headers | 37,934,529 | 36.177 |
| target static/import libraries | 31,376,423 | 29.923 |
| Clang resource headers | 15,885,819 | 15.150 |
| compiler executables | 7,012,352 | 6.688 |
| target runtime files | 1,648,640 | 1.572 |
| metadata/scripts | 1,008,243 | 0.962 |
| Python import libraries | 787,301 | 0.751 |
| Clang resource runtime | 256,660 | 0.245 |
| other | 185,585 | 0.177 |
| other compiler-bin files | 74,989 | 0.072 |

The two dominant files are `libLLVM-23.dll` (77,647,360 bytes) and
`libclang-cpp.dll` (49,632,768 bytes). Together they account for more than half
of the complete retained payload.

The qualified package's total compressed size is retained exactly. The historical
artifact did not retain an independently compressed archive for every category, so
per-category compressed numbers are not invented. Later package qualification
records compressed contribution from the actual micro-Clang package while the
Stage-AW total remains the immutable compressed reference.

## Phase decision

**GO to Phase 1.** The dominant removable cost is the shared LLVM/Clang host DLL
closure. Therefore Phase 1 first tests a source-built, X86-only, statically linked
Clang/LLD host while holding LLVM and mingw-w64/runtime revisions constant. Core
C/UCRT headers and target libraries are deliberately not aggressively pruned at
this gate.
