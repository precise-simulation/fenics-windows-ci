# Phase 4: side-by-side runtime integration

**Status:** proposed.

## Objective

Make TinyCC selectable through the existing Windows JIT runtime infrastructure without changing the default LLVM-MinGW path or the native VS2022 build toolchain.

## Backend selection

Add an explicit runtime selector, for example:

```text
FENICS_JIT_COMPILER=llvm-mingw
FENICS_JIT_COMPILER=tinycc
```

Default remains `llvm-mingw` until the final release decision.

Selection must be process-local and deterministic. Invalid or unavailable backends must fail with a clear error rather than falling through to an ambient compiler.

## Shared runtime responsibilities

Factor only genuinely shared concerns out of the current LLVM-MinGW helper:

- active Python prefix and headers;
- FFCx/UFCx include discovery;
- runtime DLL search paths;
- environment sanitization;
- diagnostics directory handling;
- backend selection/lifecycle;
- MPI child-process propagation.

Keep compiler-specific logic isolated:

- LLVM-MinGW: mingw32 backend, Clang/LLD, GNU import libraries;
- TinyCC: owned TinyCC backend, TCC headers/runtime, `.def` imports.

Avoid a large generic compiler abstraction if two small backend implementations are easier to audit.

## Package dependency policy

During this phase do not replace the existing `fenics-dolfinx -> fenics-jit-llvm-mingw` runtime dependency.

TinyCC should be installed explicitly in the experimental environment and selected only by the experiment workflow/tests.

Possible production dependency models are deferred to Phase 7:

1. LLVM-MinGW default, TinyCC optional;
2. TinyCC compact default, LLVM-MinGW fallback;
3. mutually exclusive runtime variants;
4. TinyCC rejected and not shipped.

## MPI behavior

The selected backend and package root must propagate identically to MPI child processes. A two-rank probe should verify both ranks report the same TinyCC revision, adapter type, Python ABI definition, and include roots.

Do not rely on parent-only monkey patches that are absent in newly launched Python processes.

## Cache isolation

Ensure FFCx/CFFI cache identity cannot accidentally reuse an LLVM-MinGW-generated module when TinyCC is selected, or vice versa.

Preferred approaches:

- backend identity included in JIT/cache signature; or
- backend-specific cache directory namespace.

A backend switch must force compilation at least once before subsequent same-backend cache reuse.

## Tasks

1. Introduce explicit backend selection in the owned runtime setup.
2. Factor shared environment/Python/FFCx discovery only where useful.
3. Keep LLVM-MinGW behavior unchanged under the default selector.
4. Add TinyCC package-root discovery and adapter activation.
5. Add backend-specific cache identity/isolation.
6. Verify MPI child-process selection.
7. Add diagnostics showing backend and exact compiler revision.
8. Add regression tests proving LLVM-MinGW remains unchanged.

## Exit criteria

Phase 4 passes when the same DOLFINx/FFCx caller can select LLVM-MinGW or TinyCC deterministically, the caches cannot cross-contaminate, MPI children inherit the choice, and installing/testing TinyCC requires no production metadata switch.