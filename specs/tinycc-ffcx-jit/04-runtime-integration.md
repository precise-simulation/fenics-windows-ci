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
- TinyCC: owned TinyCC compiler/build_ext backend, TCC headers/runtime, `.def` imports.

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

The selected backend and package root must propagate identically to MPI child processes. A two-rank probe should verify both ranks report the same TinyCC revision, adapter type, Python ABI definition, include roots, and backend-specific cache root.

Do not rely on parent-only monkey patches that are absent in newly launched Python processes.

## Mandatory cache isolation

LLVM-MinGW and TinyCC must use physically distinct FFCx/CFFI cache namespaces. This is a correctness requirement, not an optional optimization.

During qualification use a backend-specific cache root, conceptually:

```text
<cache>/ffcx/llvm-mingw/...
<cache>/ffcx/tinycc/...
```

The exact mechanism may be an owned JIT option or runtime-helper configuration, but the resulting physical cache roots must differ before compilation begins. Do not rely only on compiler identity being added to an existing shared cache signature during this epic.

Required behavior:

- switching `llvm-mingw -> tinycc` forces at least one TinyCC compilation before TinyCC cache reuse;
- switching `tinycc -> llvm-mingw` likewise forces an LLVM-MinGW compilation in its own namespace;
- one backend must never load a `.pyd` created by the other, even if the FFCx module name/source hash is otherwise identical;
- MPI children inherit the same backend-specific root;
- diagnostics record the resolved cache root for every JIT.

## Tasks

1. Introduce explicit backend selection in the owned runtime setup.
2. Factor shared environment/Python/FFCx discovery only where useful.
3. Keep LLVM-MinGW behavior unchanged under the default selector.
4. Add TinyCC package-root discovery and compiler/build_ext activation.
5. Implement mandatory backend-specific physical cache roots.
6. Verify backend switching forces a fresh compile before same-backend reuse.
7. Verify MPI child-process selection and cache-root propagation.
8. Add diagnostics showing backend, exact compiler revision, and resolved cache root.
9. Add regression tests proving LLVM-MinGW remains unchanged.

## Exit criteria

Phase 4 passes when the same DOLFINx/FFCx caller can select LLVM-MinGW or TinyCC deterministically, the backends use physically separate cache namespaces with demonstrated fresh compilation after a switch, MPI children inherit the choice/cache root, and installing/testing TinyCC requires no production metadata switch.
