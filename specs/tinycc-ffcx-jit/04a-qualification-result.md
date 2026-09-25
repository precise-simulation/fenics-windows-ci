# Phase 4A qualification result

**Decision:** PASS — Phase 4A private TinyCC qualification is complete and Phase 4B shared-runtime integration may begin.

## Qualified revision

- repository head: `3cd5960d9bc7437853f6cc90dcfed91d1837b722`
- workflow: `tinycc-jit` #22
- run: `34668917413`
- pinned TinyCC revision: `0fb54300b56512754221d80adda85ddb9815bceb`
- supported blocking Python matrix: 3.12, 3.13, 3.14

The exact-head `stack` workflow #253 (`34668917405`) also completed successfully after this qualification run.

## Phase 4A matrix

The installed Phase-3 `fenics-jit-tinycc` package passed the Phase-4A private qualification job on all supported interpreters:

| Python | Job result | Evidence artifact | Artifact digest |
| --- | --- | --- | --- |
| 3.12 | pass | `tinycc-phase4a-py3.12` | `sha256:868a65023549d653cea7022401d65d396760e66c0ba8cd12746d203b7d92922e` |
| 3.13 | pass | `tinycc-phase4a-py3.13` | `sha256:a0c67ecb2c6d0e78a1050e62b627ad555365c93bbadc8a81b141a814807c0885` |
| 3.14 | pass | `tinycc-phase4a-py3.14` | `sha256:cf4effff5ebdff2c4a9ddb12e86ec070fbe5c70d4439371a6e69b9dc98d55b6f` |

Each blocking job completed the following required qualification sequence successfully:

1. install the qualified Phase-3 TinyCC package;
2. install TinyCC and LLVM-MinGW side by side without changing shared-runtime ownership;
3. run the LLVM-MinGW reference form corpus;
4. run a fresh TinyCC broad private qualification;
5. reload the TinyCC private cache in a new process;
6. re-run the installed-package ABI, CRT, PE-security, and negative-input self-test.

The broad private proof covers the Phase-4A scope from `04-runtime-integration.md`, including representative generated-form coverage and numerical comparison, fresh/private-cache reuse, repeated process use, ABI/packing/bitfield/`long double` regression checks, Stable-ABI Python linking, mixed-CRT allocation stress, PE hardening/relocation/unwind checks, system-library provenance, hostile external configuration isolation, and foreign-object/library rejection.

## Package gate inherited from Phase 3

Phase 4A used the reproducible Phase-3 package artifact produced by the same run:

- artifact: `tinycc-phase3-package`
- digest: `sha256:09d59f3274a9e8c81219450bc17d6da712a7bf73feeb27507698997c74c2d5c3`

The Phase-3 package reproducibility, relocatable install, installed self-test, and early footprint gate all passed before the Phase-4A jobs were allowed to run.

## Non-blocking reference results

These results do not change the Phase-4A decision:

- TinyCC 0.9.27 formal-release reference remains non-blocking and failed during its reference bootstrap path; the qualified candidate is the pinned development revision above.
- Python 3.15 remains informational/non-blocking and did not resolve the requested FEniCS environment in this run; supported Phase-4A qualification is Python 3.12-3.14.

## Boundary of this decision

This PASS establishes only the viability-before-refactor gate required by Phase 4A. It does **not** change the production runtime architecture, default compiler backend, DOLFINx bootstrap, or package dependency shape.

The next ordered work is Phase 4B. It may now introduce the single-owner shared runtime, explicit `FENICS_JIT_COMPILER` backend selection, immutable backend-specific cache namespaces established before FFCx cache lookup, common activation serialization, side-by-side package ownership checks, MPI propagation, and LLVM-MinGW default-path regression coverage.

LLVM-MinGW remains the production default and fallback until the later release decision.
