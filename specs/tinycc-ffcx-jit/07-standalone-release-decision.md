# Phase 7: standalone proof and release decision

**Status:** proposed.

## Objective

Prove the qualified TinyCC package in the actual standalone/release context and make an explicit shipping decision relative to LLVM-MinGW.

No automatic default switch is implied by completing the earlier phases.

## Standalone staging

Stage TinyCC into the same standalone/Nuitka layout concept used for the LLVM-MinGW JIT runtime.

The test must perform a fresh FFCx JIT while:

- the original conda/build prefix is renamed, moved, or otherwise inaccessible;
- Visual Studio and host Windows SDK compiler paths are removed from the JIT environment;
- LLVM-MinGW is not available when testing TinyCC-only operation;
- compiler, TinyCC runtime headers/support, `python3.def`, CPython headers, UFCx headers, and runtime helper resolve entirely from the staged bundle.

Test a bundle path containing spaces.

## Release configurations to evaluate

### Option A: LLVM-MinGW default, TinyCC optional fallback

Use when TinyCC is correct and very small but generated-code performance is meaningfully worse.

Properties:

- normal conda/runtime keeps LLVM-MinGW;
- TinyCC can be selected explicitly for compact/diagnostic use;
- standalone profile may optionally include/select TinyCC where size is more important.

### Option B: TinyCC compact standalone backend, LLVM-MinGW normal runtime

Use when TinyCC's strongest advantage is standalone footprint and startup/JIT latency.

Properties:

- no production conda metadata change;
- standalone bundle can choose TinyCC intentionally;
- LLVM-MinGW remains the normal/reference backend.

### Option C: TinyCC default, LLVM-MinGW fallback

Only consider if Phase 6 shows generated-code performance close to LLVM-MinGW and the full validation/ABI record is at least as convincing.

This requires a separate explicit metadata/default-switch change after this epic's evidence is reviewed.

### Option D: do not ship TinyCC

Use when maintenance, ABI, runtime performance, or compatibility costs outweigh the footprint advantage. Retain the plan/results as a documented rejected experiment.

## Runtime fallback behavior

Do not silently fall back between compilers after a compile failure. A module that fails under TinyCC must fail with TinyCC diagnostics unless the caller explicitly requests another backend.

If a user-facing automatic fallback is ever desired, design it separately with cache identity, diagnostics, reproducibility, and support implications documented.

## Security and provenance

Before release:

- record exact upstream TinyCC source revision and hashes;
- include LGPL license/source compliance material;
- record local patches;
- scan/package-test the actual staged binary payload;
- ensure the standalone bundle contains no build-prefix paths or accidental compiler tools.

## Final qualification

Run from the staged bundle:

- minimal CFFI compile/import;
- fresh Poisson JIT/solve;
- representative Phase 5 forms;
- at least one two-rank MPI case if standalone MPI is supported in the target bundle;
- backend-specific cache reuse;
- PE import inspection;
- runtime benchmark spot checks.

Repeat on a clean Windows environment when practical. GitHub CI remains the reproducible acceptance path; a truly pristine VM without Visual Studio is additional confidence.

## Tasks

1. Add TinyCC to the standalone staging logic without changing the default selector initially.
2. Test with original prefix inaccessible and LLVM-MinGW absent.
3. Record incremental standalone bytes.
4. Repeat representative correctness/performance checks from the staged layout.
5. Complete licensing/source-provenance release material.
6. Write a final decision record choosing Options A-D and the reason.
7. Only after an explicit decision, make any DOLFINx dependency/default-backend change in a separate implementation PR.

## Exit criteria

Phase 7 is complete when the staged standalone TinyCC runtime performs fresh JIT hermetically and the repository records one explicit outcome: optional fallback, compact standalone backend, default candidate pending a separate switch, or rejected experiment.