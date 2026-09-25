# Phase 3 qualification result

**Status:** done.

This result records completion of the reproducible `fenics-jit-tinycc` package gate defined by `03-runtime-package.md`.

## Qualified implementation

- Pull request: #11 (`impl/tinycc-ffcx-jit-phase1`).
- Qualified TinyCC revision: `0fb54300b56512754221d80adda85ddb9815bceb`.
- Qualification run: `tinycc-jit` #17, run ID `34663777306`, head `568a3357a1bde8d1b17225c2c76e0bb144898df3`.
- Package: `fenics-jit-tinycc` `0.9.28rc0`, build `h9490d1a_0`.
- Build tool: `rattler-build` 0.74.0 on `windows-2022`.
- Bootstrap compiler contract: `vs2022_win-64 19.44.*`; observed compiler `Microsoft (R) C/C++ Optimizing Compiler Version 19.44.35228 for x64`.

## Reproducibility and provenance

The package build pins the complete compiler-production contract used by this phase:

- TinyCC source revision `0fb54300b56512754221d80adda85ddb9815bceb`;
- upstream Windows build-script SHA-256 `fea97a1ad5e9bdb866394d4e5d0bc1f5ded61d8381379908705f7580025fd958`;
- deterministic patched build-script SHA-256 `52e26b204d4c0273980ac057b9066d7e391d855b74f56c3499dd1626dfb3508a`;
- local deterministic build policy `build-tcc-msvc-repro-v3` (`-Zi` removed, deterministic source-path mapping enabled, linker `-Brepro` enabled);
- `tcc.exe` SHA-256 `0daaa68c632bb1129d9a0bcc3a2c58335a47c60f1ef7bb91d07734d6a79c0416`;
- `libtcc.dll` SHA-256 `c2323c5009bb2275792b8fe31bd322474721bc08cdf3c8327da2d2f9f8cc3ed1`;
- adapter SHA-256 `87d0340ac0aa23c60d61a5b4f5be9cd7557c3a267e03ac4cc8c7c9d271203574`;
- backend cache identity `tinycc-0fb54300b565-aaa86e30769a96f90b37`.

Two clean package builds were installed into separate prefixes containing spaces. Their 112-file installed backend manifests, sizes, and SHA-256 hashes match exactly. The `.conda` container sizes differ slightly because archive/package metadata is not part of the installed payload reproducibility contract; the installed semantic payload is reproducible.

## Package ownership and runtime contract

The package owns only `Library/fenics-jit/backends/tinycc/**`. The Phase-3 manifest check rejects any file beneath `Library/fenics-jit/runtime/**` or outside the TinyCC backend root, so the package does not compete with the future common runtime owner.

Runtime dependencies are constrained to the qualified compatibility contract:

```text
python >=3.12,<3.15
cffi 2.1.*
setuptools 84.*
```

Visual Studio/Windows SDK packages are build-time bootstrap inputs only, not `fenics-jit-tinycc` runtime dependencies. The installed-package adapter command audit rejects `cl.exe`, `link.exe`, Clang, GCC, Visual Studio paths, and Windows Kits paths from JIT compilation.

## Installed-package qualification

Both clean installed packages pass the backend self-test, including:

- direct CFFI source-to-`.pyd` compilation through the owned adapter;
- fresh FFCx/DOLFINx Poisson JIT and solve;
- Stable-ABI `python3.dll` import with no minor-version Python import;
- `DYNAMIC_BASE`, `HIGH_ENTROPY_VA`, and `NX_COMPAT` PE characteristics;
- relocation and x64 `.pdata` metadata;
- mixed-CRT policy with `msvcrt.dll` confined to the qualified boundary;
- `-mms-bitfields` ABI result and 8-byte/8-byte-aligned Windows `long double` model;
- foreign-object rejection;
- nested activation restoration and cross-thread activation serialization;
- relocation to install prefixes containing spaces;
- absence of build-prefix/Visual-Studio/Windows-SDK paths from backend runtime metadata.

The installed Poisson solve produced solution norm `0.3257159634482999` and two generated `.pyd` modules in the private FFCx cache.

## Footprint gate

Measured backend payload:

- installed payload: **2,294,374 bytes (2.188 MiB)**;
- compressed build A: **626,388 bytes**;
- compressed build B: **626,283 bytes**;
- Phase-3 early gate: **56,735,825 bytes (54.107 MiB)**, equal to 25% of the qualified 216.43 MiB LLVM-MinGW Stage-AW installed baseline.

The TinyCC backend is about 1.0% of the LLVM-MinGW installed baseline and passes the early footprint gate with substantial margin.

## Phase decision

**GO.** Phase 3 is complete. Phase 4A may now run broad private installed-package qualification while leaving the qualified LLVM-MinGW production runtime/bootstrap/dependency architecture unchanged. Phase 4B remains prohibited until the Phase-4A viability gate passes.
