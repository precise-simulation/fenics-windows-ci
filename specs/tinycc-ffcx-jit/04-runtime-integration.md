# Phase 4: single-owner runtime and side-by-side backend integration

**Status:** proposed.

## Objective

Make TinyCC selectable through the Windows JIT runtime infrastructure without changing the default LLVM-MinGW path or the native VS2022 build toolchain, while eliminating shared-file ownership conflicts between compiler packages and centralizing safe activation semantics.

## Runtime ownership split

Before both compiler packages coexist in a production environment, factor common JIT lifecycle/selection code into a uniquely owned runtime component, provisionally:

```text
fenics-jit-runtime
  Library/fenics-jit/runtime/...

fenics-jit-llvm-mingw
  Library/fenics-jit/backends/llvm-mingw/...

fenics-jit-tinycc
  Library/fenics-jit/backends/tinycc/...
```

Required ownership rules:

- only `fenics-jit-runtime` owns `Library/fenics-jit/runtime/...`;
- LLVM-MinGW and TinyCC packages own only their backend subtrees;
- installing/uninstalling one compiler backend cannot overwrite/remove common runtime files or the other backend;
- TinyCC-only standalone operation depends on the shared runtime package/component, not on LLVM-MinGW merely to obtain the helper;
- update the DOLFINx Windows bootstrap to load the shared runtime component and emit backend-neutral error messages.

If implementation evidence shows a separate `fenics-jit-runtime` conda package is unnecessarily costly, an equivalent single-owner bootstrap may live in DOLFINx, but compiler packages still must not overlap files. Record any deviation explicitly before Phase 4 is marked complete.

## Backend selection

Add an explicit runtime selector:

```text
FENICS_JIT_COMPILER=llvm-mingw
FENICS_JIT_COMPILER=tinycc
```

Default remains `llvm-mingw` until the final release decision.

Selection must be deterministic. Invalid or unavailable backends must fail with a clear error rather than falling through to an ambient compiler.

## Shared runtime responsibilities

Factor only genuinely shared concerns out of the current LLVM-MinGW helper:

- backend selection and backend-root discovery;
- active Python prefix and headers;
- FFCx/UFCx include discovery;
- runtime DLL search paths;
- environment sanitization;
- process-wide activation serialization and nested-activation policy;
- diagnostics directory handling;
- backend-specific cache-root selection **before FFCx cache lookup**;
- backend lifecycle;
- MPI child-process propagation.

Keep compiler-specific logic isolated:

- LLVM-MinGW: mingw32 backend, Clang/LLD, GNU import libraries;
- TinyCC: owned TinyCC build_ext/compiler backend, TCC headers/runtime, `.def` imports, `-mms-bitfields`/ABI policy, strict foreign-binary rejection, system-library policy, qualified CRT/PE-hardening configuration.

Avoid a large generic compiler abstraction if two small backend implementations are easier to audit.

## Activation serialization

Both backends can require temporary process-global state, including environment variables and CFFI/setuptools hooks. The common runtime owns serialization so backend implementations cannot race each other.

Use one process-wide reentrant lock with explicit activation ownership:

- acquire the lock before mutating any process-global JIT/compiler-selection state;
- retain it until all environment/hooks are restored;
- same-thread nesting of the same backend is permitted only when restoration semantics are proven safe;
- conflicting nested activation for a different backend fails clearly rather than silently switching compiler identity;
- another thread attempting a JIT waits for the active owner and then performs its complete activation independently;
- all restoration is in `finally` paths;
- diagnostics can report active backend, owner thread identity, and nesting depth in verbose mode without making thread IDs part of cache identity.

Do not rely on the GIL as a substitute for this lock. Standard CPython threads can interleave around subprocess launches and I/O.

The shared runtime should expose the lock/nesting mechanism to backend code rather than letting each backend invent a separate lock. This prevents a TinyCC activation and LLVM-MinGW activation from interleaving their process-global mutations.

## Package dependency policy

During the start of this phase do not replace the existing `fenics-dolfinx -> fenics-jit-llvm-mingw` runtime dependency until the shared-runtime split is implemented and qualified.

The target production dependency shape for the existing default is conceptually:

```text
fenics-dolfinx
  -> fenics-jit-runtime
  -> fenics-jit-llvm-mingw
```

TinyCC is installed explicitly for the experimental environment:

```text
fenics-jit-tinycc
  -> fenics-jit-runtime
```

Exact conda metadata may differ if the common runtime is embedded in DOLFINx rather than a separate package; file ownership must remain single-source either way.

Possible final backend policies remain deferred to Phase 7:

1. LLVM-MinGW default, TinyCC optional;
2. TinyCC compact default, LLVM-MinGW fallback;
3. mutually exclusive backend variants;
4. TinyCC rejected and not shipped.

## MPI behavior

The selected backend and package root must propagate identically to MPI child processes. A two-rank probe should verify both ranks report the same TinyCC revision, adapter type, Python ABI definition, include roots, backend-specific cache root, Windows ABI/bitfield policy, system-library policy, and CRT/backend identity.

Do not rely on parent-only monkey patches that are absent in newly launched Python processes.

## Mandatory cache isolation

LLVM-MinGW and TinyCC must use physically distinct FFCx/CFFI cache namespaces. This is a correctness requirement, not an optional optimization.

FFCx 0.11 performs `get_cached_module(...)` before entering CFFI/setuptools compilation. Therefore cache isolation must be resolved in the shared DOLFINx/JIT wrapper **before** calling `ffcx.codegeneration.jit.compile_forms(...)` or `compile_expressions(...)`. Implementing isolation only inside the later compiler/build_ext adapter is too late because a module from the other backend could already have been loaded.

During qualification use a backend-specific cache root, conceptually:

```text
<cache>/ffcx/llvm-mingw/...
<cache>/ffcx/tinycc/...
```

The shared runtime should derive the effective `jit_options["cache_dir"]` (or equivalent owned option) before FFCx cache lookup begins.

Required behavior:

- switching `llvm-mingw -> tinycc` forces at least one TinyCC compilation before TinyCC cache reuse;
- switching `tinycc -> llvm-mingw` likewise forces an LLVM-MinGW compilation in its own namespace;
- one backend must never load a `.pyd` created by the other, even if the FFCx module name/source hash is otherwise identical;
- the backend-specific root is established before any cache existence/ready-file check;
- MPI children inherit the same backend-specific root;
- diagnostics record the resolved cache root for every JIT.

Backend selection itself does not need to become part of FFCx's source hash when physically distinct roots enforce isolation, but the selected backend identity must be recorded in diagnostics.

## Concurrency validation

Add runtime-level tests that exercise the common lock rather than only the TinyCC adapter in isolation:

- two Python threads performing TinyCC JIT requests concurrently;
- two Python threads performing LLVM-MinGW JIT requests concurrently;
- one TinyCC and one LLVM-MinGW request started concurrently;
- same-thread same-backend nested activation;
- same-thread conflicting-backend nested activation, which must fail deterministically;
- compile failure/exception paths followed by a successful activation to prove restoration;
- cache diagnostics proving each completed JIT used the intended backend/cache root.

The expected policy is serialized in-process compilation, not parallel mutation of process-global CFFI/setuptools state.

## Tasks

1. Introduce the single-owner common runtime/bootstrap layout and migrate the existing LLVM-MinGW helper without behavior change.
2. Update DOLFINx's Windows bootstrap to load the common runtime component with backend-neutral diagnostics.
3. Introduce explicit backend selection.
4. Move activation serialization/nesting into the shared runtime and preserve the Phase-2 TinyCC semantics.
5. Factor shared environment/Python/FFCx discovery only where useful.
6. Keep LLVM-MinGW behavior unchanged under the default selector.
7. Add TinyCC backend-root discovery and owned build_ext/compiler activation.
8. Implement backend-specific physical cache roots before FFCx `compile_forms`/`compile_expressions` cache lookup.
9. Verify backend switching forces a fresh compile before same-backend reuse.
10. Verify thread concurrency and same/conflicting nested activation semantics across both backends.
11. Verify MPI child-process selection and cache-root propagation.
12. Add diagnostics showing backend, exact compiler revision, Windows ABI/bitfield policy, system-library policy, CRT identity, and resolved cache root.
13. Add package-file ownership tests proving no overlap between common runtime and backend packages.
14. Add regression tests proving LLVM-MinGW remains unchanged.

## Exit criteria

Phase 4 passes when the same DOLFINx/FFCx caller can select LLVM-MinGW or TinyCC deterministically; common runtime files have exactly one owner; compiler packages install into non-overlapping backend roots; all temporary process-global JIT state is serialized through a single restoration-safe reentrant activation mechanism; conflicting nested backends fail clearly; the backends use physically separate cache namespaces established before FFCx's cache lookup with demonstrated fresh compilation after a switch; MPI children inherit the choice/cache root; TinyCC-only operation does not depend on LLVM-MinGW for shared runtime code; and installing/testing TinyCC does not change the default backend.
