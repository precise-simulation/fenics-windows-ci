# Phase 4B qualification result

**Decision:** PASS — Phase 4B shared-runtime integration is qualified on the supported Python 3.12-3.14 matrix.

## Qualified revision

- repository head: `651a4f47f4d033c5fa2a31ef0b578bd8e1752c74`
- branch: `impl/tinycc-ffcx-jit-phase1`
- workflow: `tinycc-jit` #59
- run: `34972166167`
- principal regression workflow: `stack` #294
- principal regression run: `34972166147`
- pinned TinyCC revision: `0fb54300b56512754221d80adda85ddb9815bceb`
- supported blocking Python matrix: 3.12, 3.13, 3.14

Both automatic workflows completed successfully on the exact same repository head above. No manual rerun or duplicate workflow dispatch is part of this qualification evidence.

## Supported matrix

The Phase-4A private qualification jobs embedded in the Phase-4B integration run passed on every blocking interpreter:

| Python | Phase 4A result |
| --- | --- |
| 3.12 | pass |
| 3.13 | pass |
| 3.14 | pass |

The same run also passed the Phase-3 package reproducibility/footprint gate before the Phase-4A jobs were allowed to execute.

Python 3.14 exercised the Task-15 MPI LLVM-MinGW path that had exposed two qualification-harness issues during Phase-4B minimization: equivalent Windows extended-path spellings across MPI ranks, and setuptools' relative `Release` build-temp directory. The final proof canonicalizes Windows paths only for cross-rank equality while preserving raw diagnostic evidence, pre-creates the Python-3.14 LLVM-MinGW proof build directory, and retains a 180-second MPI subprocess timeout so a failed rank cannot leave CI hung indefinitely. These are proof-harness safeguards; they do not change production selector, backend, compiler, DOLFINx, packaging, or workflow behavior.

## Phase 4B qualification evidence

The Phase-4B implementation satisfies the runtime-integration exit criteria from `04-runtime-integration.md`:

1. **Single-owner shared runtime and package ownership.** Common runtime/control-plane files are owned by `fenics-jit-runtime`; LLVM-MinGW and TinyCC own separate backend payloads, and qualification checks package ownership/dependency direction so the shared runtime does not depend on a compiler backend.
2. **Deterministic backend selection.** The same DOLFINx/FFCx caller can select `llvm-mingw` or `tinycc` through the shared selector. LLVM-MinGW remains the default, and unavailable/invalid backend selection does not silently fall through to an ambient compiler.
3. **Immutable cache identity and switching.** Each backend has its own deterministic backend-cache-id and physical cache namespace established before FFCx cache lookup. Switching backends forces compilation in the destination namespace before same-identity cache reuse, and the default LLVM path remains isolated from TinyCC.
4. **Restoration-safe shared lifecycle.** Shared activation owns serialization, same-backend nesting, conflicting-backend rejection, environment restoration, and installed-package lifecycle behavior. Branch JIT packages are installed/upgraded atomically for qualification.
5. **Concurrency.** Runtime qualification exercises concurrent TinyCC/TinyCC, LLVM-MinGW/LLVM-MinGW, and mixed-backend requests through the common serialization mechanism and verifies restoration after failure paths.
6. **MPI propagation.** A two-rank proof passes for both `llvm-mingw` and `tinycc`. Both ranks agree on selected backend, backend cache identity, backend root, physical cache root, generated-module snapshot, and required backend diagnostic identity while using the same physical cache successfully.
7. **Truthful diagnostics.** MPI/shared-runtime evidence includes compiler revision, adapter/backend cache identity, CRT identity, external-configuration policy, system-library policy, Windows ABI policy including bitfield/`long double` semantics, include roots, Python ABI definition, and resolved cache root.
8. **Default LLVM-MinGW regression.** The default selector remains LLVM-MinGW and the exact-head `stack` principal regression workflow passes, demonstrating that TinyCC integration did not regress the production default path.

## Task-15 MPI evidence

Task 15 has positive supported-matrix evidence rather than only selector-level assertions. On Python 3.13, both `llvm-mingw` and `tinycc` completed the two-rank MPI proof, with both ranks using the same physical cache and successfully loading the generated module. Python 3.14 subsequently completed the same Phase-4A qualification path after the proof-only build-directory correction described above.

The MPI comparison intentionally treats equivalent Windows path spellings such as `D:\\...` and `\\\\?\\D:\\...` as the same physical path while retaining the original raw strings in evidence.

## Non-blocking reference results

These expected results do not change the Phase-4B decision:

- TinyCC 0.9.27 formal-release reference remains non-blocking and fails in its reference bootstrap path; the qualified backend is the pinned development revision above.
- Python 3.15 preview remains informational/non-blocking and does not currently resolve the supported FEniCS environment; the blocking qualification matrix is Python 3.12-3.14.

## Boundary of this decision

This PASS records completion of the Phase-4B shared-runtime integration gate. It does not change the release-policy decision deferred to Phase 7, does not make TinyCC the default, and does not merge or mark PR #11 ready for review.

LLVM-MinGW remains the production default. Any later phase must preserve the ordered epic gates and begin only from a separately qualified exact-head CI cycle.
