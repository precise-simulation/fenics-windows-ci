# Phase 7: standalone proof and release decision

**Status:** proposed.

## Objective

Prove the qualified TinyCC backend in the actual standalone/release context and make an explicit shipping decision relative to LLVM-MinGW.

No automatic default switch is implied by completing the earlier phases.

## Standalone staging

Stage the common Windows JIT runtime plus the TinyCC backend into the same standalone/Nuitka layout concept used for the LLVM-MinGW JIT runtime.

The staged layout must preserve single ownership:

```text
<bundle>/fenics-jit/runtime/...
<bundle>/fenics-jit/backends/tinycc/...
```

LLVM-MinGW's backend subtree must be removable for the TinyCC-only proof without removing the common selector/helper.

The test must perform a fresh FFCx JIT while:

- the original conda/build prefix is renamed, moved, or otherwise inaccessible;
- Visual Studio and host Windows SDK compiler paths are removed from the JIT environment;
- LLVM-MinGW is not available when testing TinyCC-only operation;
- the common runtime selector is still available from its own staged owner;
- compiler, TinyCC runtime headers/support, `python3.def`, CPython headers, UFCx headers, and runtime helper resolve entirely from the staged bundle;
- the backend-specific TinyCC cache root is chosen before FFCx cache lookup.

Test a bundle path containing spaces.

## Release configurations to evaluate

### Option A: LLVM-MinGW default, TinyCC optional fallback

Use when TinyCC is correct and very small but generated-code performance is meaningfully worse.

Properties:

- normal conda/runtime keeps LLVM-MinGW as default;
- TinyCC can be selected explicitly for compact/diagnostic use;
- common runtime remains single-owned;
- standalone profile may optionally include/select TinyCC where size is more important.

### Option B: TinyCC compact standalone backend, LLVM-MinGW normal runtime

Use when TinyCC's strongest advantage is standalone footprint and startup/JIT latency.

Properties:

- no default compiler metadata switch for normal installs;
- standalone bundle can include common runtime + TinyCC backend without LLVM-MinGW;
- LLVM-MinGW remains the normal/reference backend.

### Option C: TinyCC default, LLVM-MinGW fallback

Only consider if Phase 6 shows generated-code performance close to LLVM-MinGW and the full validation/ABI/security record is at least as convincing.

This requires a separate explicit metadata/default-switch change after this epic's evidence is reviewed.

### Option D: do not ship TinyCC

Use when maintenance, ABI/CRT/security, runtime performance, or compatibility costs outweigh the footprint advantage. Retain the plan/results as a documented rejected experiment.

## Runtime fallback behavior

Do not silently fall back between compilers after a compile failure. A module that fails under TinyCC must fail with TinyCC diagnostics unless the caller explicitly requests another backend.

If a user-facing automatic fallback is ever desired, design it separately with cache identity, diagnostics, reproducibility, and support implications documented.

## Security and provenance

Before release:

- record exact upstream TinyCC source revision and hashes;
- include LGPL license/source compliance material;
- record local CRT/compatibility/PE-hardening patches;
- scan/package-test the actual staged binary payload;
- ensure the standalone bundle contains no build-prefix paths or accidental compiler tools;
- verify generated `.pyd` modules retain the qualified CRT imports and PE mitigation/relocation/unwind properties from Phases 1 and 5.

## Final qualification

Run from the staged bundle:

- minimal CFFI compile/import;
- fresh Poisson JIT/solve;
- representative Phase 5 forms;
- at least one two-rank MPI case if standalone MPI is supported in the target bundle;
- backend-specific cache reuse and backend-switch isolation where both backends are staged;
- PE import/export, CRT, mitigation, relocation, and unwind inspection;
- foreign-object/library rejection spot checks;
- runtime benchmark spot checks.

Repeat on a clean Windows environment when practical. GitHub CI remains the reproducible acceptance path; a truly pristine VM without Visual Studio is additional confidence.

## Tasks

1. Stage the single-owner common runtime and TinyCC backend without changing the default selector initially.
2. Test with original prefix inaccessible and LLVM-MinGW backend absent while the common runtime remains present.
3. Verify no staged file ownership overlap between common runtime, TinyCC, and LLVM-MinGW backend payloads.
4. Record common-runtime bytes separately from TinyCC incremental standalone bytes.
5. Repeat representative correctness/performance/security checks from the staged layout.
6. Complete licensing/source-provenance release material.
7. Write a final decision record choosing Options A-D and the reason.
8. Only after an explicit decision, make any DOLFINx dependency/default-backend change in a separate implementation PR.

## Exit criteria

Phase 7 is complete when the staged common runtime + TinyCC backend performs fresh JIT hermetically with LLVM-MinGW absent, shared files remain independently owned, the qualified CRT/PE-security/object-boundary properties still hold, and the repository records one explicit outcome: optional fallback, compact standalone backend, default candidate pending a separate switch, or rejected experiment.
