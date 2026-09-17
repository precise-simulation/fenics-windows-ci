# Phase 5 qualification result

**Decision:** PASS — Phase 5 broad integrated functional validation is qualified on the supported Python 3.12-3.14 matrix.

## Qualified revision

- repository head: `19bdb7891c7bda67fb0488a3e59c6c5f119b5190`
- branch: `impl/tinycc-ffcx-jit-phase1`
- workflow: `tinycc-jit` #75
- run: `35187385183`
- principal regression workflow: `stack` #311
- principal regression run: `35187385180`
- pinned TinyCC revision: `0fb54300b56512754221d80adda85ddb9815bceb`
- supported blocking Python matrix: 3.12, 3.13, 3.14

Both automatic workflows completed successfully on the exact same repository head above. No manual rerun or duplicate workflow dispatch is part of this qualification evidence.

## Supported matrix

The integrated TinyCC qualification path passed on every blocking interpreter:

| Python | Phase 5 result |
| --- | --- |
| 3.12 | pass |
| 3.13 | pass |
| 3.14 | pass |

The same `tinycc-jit` run also passed the pinned TinyCC bootstrap, Phase-1 compatibility proof, Phase-2 adapter qualification, Phase-3 package reproducibility/footprint gate, and installed Phase-4A broad private qualification before accepting the Phase-5 result.

## Phase 5 qualification evidence

The qualified implementation satisfies the exit criteria from `05-functional-validation.md`:

1. **Broad shared-runtime FFCx/CFFI matrix.** The TinyCC backend reuses the LLVM-MinGW Phase-5 form corpus and numerical assertions through the shared runtime, covering fresh compile/cache reload, scalar Poisson, vector/tensor, cell/interior/exterior-facet, coefficient/constant-heavy, higher-order, spaced-path, and generated-module inspection paths.
2. **Numerical equivalence.** The same reference form corpus is run under LLVM-MinGW and TinyCC with the existing numerical tolerances unchanged; the supported matrix completed without compiler-specific solve, NaN/Inf, vector/matrix, or error-norm regressions.
3. **Durable generated-source contract.** `tests/tinycc/generated-corpus/manifest.json` records the deterministic generated-C corpus for Python 3.12-3.14, including eight logical modules per supported interpreter, normalized source SHA-256 identities, package/generator identities, TinyCC/backend policy, and validator identities. `phase5-corpus-evidence.py` regenerates and hash-checks this contract during qualification rather than relying on expiring Actions artifacts.
4. **Installed-package ABI and Windows target model.** Qualification re-runs the installed package ABI/CRT/PE self-test, preserving the qualified Win64 width model, `_WIN64`/`MS_WIN64` compatibility path, `-mms-bitfields` policy, packing/bitfield contract, calling-convention probes, and the known TinyCC `long double` boundary.
5. **Cache and backend isolation.** Shared-runtime tests retain physical backend-specific cache roots selected before FFCx lookup, fresh destination-backend compilation across LLVM-MinGW/TinyCC switching, same-backend cache reuse, and process-restart cache reload behavior.
6. **Concurrency and lifecycle restoration.** The shared activation lock covers concurrent TinyCC/TinyCC and mixed TinyCC/LLVM-MinGW requests, same-backend nesting, deterministic conflicting-backend rejection, failure restoration, and restoration of process-global CFFI/setuptools/environment state.
7. **MPI.** The installed qualification path retains the two-rank shared-cache/backend-identity proof through the shared runtime, including cache-root propagation and generated-module agreement.
8. **CFFI interception and external configuration.** The owned CFFI `Distribution` interception remains selected for TinyCC; hostile external distutils/setuptools configuration is suppressed, and backend switching restores hooks/config state without ambient compiler fallback.
9. **Stable-ABI Python link integrity.** Supported modules continue to request and import `python3.dll` rather than `python312`, `python313`, `python314`, or another minor-version Python DLL. Command capture and final PE inspection remain authoritative across the supported matrix.
10. **CRT/system-library boundary.** The qualified mixed-CRT ownership model and approved Windows system-DLL resolution policy remain intact, with no Visual Studio, Windows SDK development library, Python `libs`/`PCbuild`, or arbitrary ambient library directory admitted into the TinyCC link path.
11. **PE mitigation/relocation/unwind integrity.** Generated modules retain the qualified dynamic-base, high-entropy-VA, NX, relocation, import, and x64 unwind/`.pdata` properties established by the earlier gates.
12. **Strict foreign-input boundary.** Phase 5 now explicitly rejects versioned/unsupported CFFI libraries, MSVC `.lib`, foreign `.obj`/`.o`, arbitrary `.a`, unsupported extra-object types, and host SDK/MSVC/Python development library directories before any subprocess/compiler invocation or command log can be produced.
13. **No default-backend regression.** Exact-head `stack` #311 passed, so the production LLVM-MinGW default path remains qualified alongside the TinyCC experiment.

## Generated-corpus contract correction

Run `tinycc-jit` #74 exposed a contract-maintenance issue rather than a runtime failure: the new Phase-5 hostile-input validation changed the TinyCC validator file identity while the generated C corpus remained byte-for-byte unchanged. The manifest was corrected to record the new validator SHA-256:

`d5b5fe8d3753713f0d6dd8454d5f7ac2cfbff6e06faa3bb1d83508438cf3b1af`

The eight generated-module identities and normalized source hashes for each supported Python version were unchanged. Exact-head run #75 then passed the regenerated corpus contract and the complete supported matrix.

## Non-blocking reference results

These expected results do not change the Phase-5 decision:

- TinyCC 0.9.27 formal-release reference remains non-blocking and fails in its reference bootstrap path; the qualified backend is the pinned development revision above.
- Python 3.15 preview remains informational/non-blocking and currently fails while resolving/installing the supported FEniCS runtime environment; the blocking qualification matrix remains Python 3.12-3.14.

## Boundary of this decision

This PASS records completion of the Phase-5 integrated-coverage gate. The next ordered gate is Phase 6, `06-size-performance-comparison.md`, which measures final installed/compressed/standalone footprint, JIT latency, and generated-code performance against the immutable LLVM-MinGW reference before any release/default decision.

This qualification does not make TinyCC the production default, does not change the Phase-7 release-policy decision, and does not merge or mark PR #11 ready for review. LLVM-MinGW remains the production default and TinyCC remains opt-in while the remaining ordered gates are evaluated.
