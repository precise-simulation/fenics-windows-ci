# Phase 2 qualification result

**Status:** done.

This result records completion of the owned TinyCC CFFI adapter contract defined by `02-cffi-adapter.md`.

## Qualified implementation

- Pull request: #12 (`impl/tinycc-ffcx-jit-phase2`), stacked on the qualified Phase-1 branch.
- Qualified TinyCC development revision: `0fb54300b56512754221d80adda85ddb9815bceb`.
- Final Phase-2 qualification run: `tinycc-jit` #7, run ID `34656235044`, head `8a043f61d74ae851ef216da508b9ab60c1c473c3`.
- Supported matrix: CPython 3.12, 3.13, and 3.14.
- CPython 3.15 remains informational/non-blocking because the configured channels do not yet provide a compatible `fenics-dolfinx` environment.
- TinyCC 0.9.27 remains the non-blocking historical reference established in Phase 1; the pinned development revision remains the backend baseline.

## Gate outcome

The supported matrix passes both the Phase-2 adapter-contract tests and the complete Phase-1 functional/ABI/security regression proof. The production adapter contract now includes:

- deterministic backend cache identity containing the TinyCC revision plus explicit adapter, external-config, ABI, Python-link, CRT, system-library, and PE-hardening policy versions;
- the owned `cffi._shimmed_dist_utils.Distribution` interception and direct source-to-`.pyd` `TinyCCBuildExt` path;
- suppression of ambient distutils/setuptools configuration;
- a process-wide reentrant activation lock with same-backend nesting, conflicting nested-backend rejection, cross-thread serialization, and exception-safe restoration;
- explicit rejection of unsupported important compile/link inputs, foreign binary objects/libraries, ambient library directories, and versioned Python libraries;
- stable operation with paths containing spaces and diagnostics directories that do not affect backend cache identity;
- recorded CFFI/setuptools versions and activation ownership diagnostics;
- preservation of the qualified `-mms-bitfields`, Win64 CPython model, Stable-ABI `python3.dll`, mixed-CRT ownership, system-DLL policy, and hardened x64 PE contract from Phase 1.

The initial Phase-2 CI attempt used the GitHub runner system Python for the standalone adapter-contract test and therefore could not import `cffi`. Commit `8a043f61d74ae851ef216da508b9ab60c1c473c3` corrected only the workflow invocation to use the qualified micromamba environment's `python.exe`; the supported matrix then passed.

## Deferred cross-backend case

The Phase-2 spec explicitly defers TinyCC-vs-LLVM-MinGW conflicting/racing activation tests until Phase 4B provides the shared runtime selector. Phase 2 qualifies TinyCC's private activation serialization/restoration contract without prematurely changing the production LLVM-MinGW runtime.

## Phase decision

**GO.** Phase 2 is complete and the epic may proceed to Phase 3 (`03-runtime-package.md`). Phase 3 must package the qualified adapter/toolchain as reproducible `fenics-jit-tinycc`, preserve the backend identity and ownership contracts, and satisfy the early installed-footprint gate before runtime integration proceeds.
