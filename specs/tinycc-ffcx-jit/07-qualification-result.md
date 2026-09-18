# Phase 7 qualification result

**Decision:** COMPLETE — select **Option B: TinyCC compact standalone backend, LLVM-MinGW normal/reference runtime**.

## Qualified implementation

- Pull request: #11 (`impl/tinycc-ffcx-jit-phase1`).
- implementation head: `9fd4e17816410a003771139d10a6101418f7bf8f`.
- Phase-7 workflow: `tinycc-phase7` #27, run `35352172350`.
- Phase-7 evidence artifact: `tinycc-phase7-standalone`, artifact `10550733508`.
- artifact SHA-256: `2e221fd584860b818b592476e5e05e4db2daf66141cf02821bbb2503a281c46a`.
- TinyCC regression workflow at the same head: `tinycc-jit` #108, run `35352172351`, successful.
- qualified TinyCC revision: `0fb54300b56512754221d80adda85ddb9815bceb`.
- backend cache identity: `tinycc-0fb54300b565-aaa86e30769a96f90b37`.

The supported Python 3.12-3.14 TinyCC compatibility jobs pass at this head. The formal TinyCC 0.9.27 reference and Python 3.15 preview remain the previously documented non-blocking failures.

## Hermetic standalone result

The TinyCC-only Nuitka bundle passes the Phase-7 hermetic proof with the original conda/build prefix renamed and inaccessible.

The proof confirms:

- LLVM-MinGW is absent from the standalone JIT backend tree;
- the common runtime selector remains independently staged;
- no forbidden host compiler executable is present in the bundle;
- all captured TinyCC include paths resolve inside the standalone bundle;
- CPython headers, UFCx headers, `python3.def`, TinyCC runtime support, and the shared runtime resolve from the bundle;
- the physical FFCx cache is rooted under `ffcx/tinycc/<backend-cache-id>` before cache lookup;
- a minimal CFFI module compiles and imports;
- a foreign `.obj` input is rejected by the TinyCC adapter before it can become a supported interchange path;
- a fresh Poisson form compiles and solves;
- cache reuse succeeds without a second compile;
- representative higher-order and interior/exterior-facet forms compile from the standalone layout.

The serial proof generated four FFCx cache modules plus the minimal CFFI module. All five inspected modules import the Stable-ABI `python3.dll` and the qualified `msvcrt.dll` CRT boundary, have DLL characteristics `0x160` (`DYNAMIC_BASE`, `HIGH_ENTROPY_VA`, and `NX_COMPAT`), and contain both relocation and x64 unwind metadata.

The representative Poisson solve produced solution norm `0.4922541639224417`. First use was about `0.1465 s` and cache reuse about `0.00244 s` in this CI run; these are spot-check values, not a replacement for the Phase-6 benchmark.

## Standalone MPI result

The target bundle contains Intel MPI runtime support, so Phase 7 also runs the required two-rank standalone case through the staged `mpiexec.exe`.

The two-rank proof passes with:

- exactly two ranks;
- identical TinyCC backend/cache identity on both ranks;
- compiler-command counts `[1, 0]`: rank 0 performs the fresh JIT compile and rank 1 does not start an independent compiler;
- both ranks observing the same generated cache module;
- the original build prefix still inaccessible;
- the rank-0 TinyCC command using only bundle-owned compiler, headers, and `python3.def`;
- the generated MPI cache module importing `python3.dll` and retaining the same `0x160` mitigation flags, relocation metadata, and `.pdata` unwind metadata.

This closes the standalone-MPI condition in the Phase-7 specification.

## Standalone footprint

The Phase-7 bundle records ownership separately:

| Component | Bytes |
| --- | ---: |
| common JIT runtime | 63,327 |
| TinyCC backend payload | 2,341,076 |
| staged CPython/UFCx development headers | 1,274,080 |

The compiler/backend remains tiny relative to the immutable Stage-AW LLVM-MinGW installed baseline of 216.43 MiB. Phase 6 already measured the integrated TinyCC backend at about 1% of that baseline and found roughly 4-5x faster cold JIT compilation in the representative corpus.

## Provenance and licensing

Release provenance remains package-owned and reproducible:

- exact TinyCC source revision is pinned;
- upstream and locally patched Windows build-script SHA-256 values are recorded;
- the deterministic local build policy and bootstrap compiler contract are recorded;
- `tcc.exe`, `libtcc.dll`, adapter, runtime integration, and backend cache identity are recorded in package metadata;
- TinyCC LGPL-2.1 license material is staged as `licenses/TinyCC-COPYING`;
- the installed backend package owns only `Library/fenics-jit/backends/tinycc/**`, while the common runtime is independently owned.

The Phase-3 reproducibility result remains the detailed provenance record.

## Release decision

**Option B is selected.**

TinyCC's strongest advantages are its very small compiler footprint and substantially lower cold-JIT latency. The Phase-7 standalone proof shows that those advantages survive the actual Nuitka release layout without LLVM-MinGW or the original conda prefix, including a two-rank MPI JIT.

TinyCC is **not** selected as the normal/default backend. Phase 6 found a persistent generated-code performance tradeoff: the higher-order P3 family was about `4.4x` slower at the aggregate median, while other representative family medians ranged from about `1.27x` to `2.75x`. That excludes Option C under the epic's default-candidate criteria.

Therefore:

- normal/runtime installations keep LLVM-MinGW as the default/reference backend;
- TinyCC remains explicitly selectable where desired;
- the compact standalone profile may ship the common runtime + TinyCC backend without LLVM-MinGW;
- no silent compiler fallback is introduced;
- no DOLFINx default-backend dependency switch is made by this decision.

Phase 7 and the TinyCC epic are complete. Any future default switch, automatic fallback policy, Python 3.15 promotion, or materially different TinyCC compiler revision requires a separate qualification/change.
