# Phase 4: single-owner runtime and side-by-side backend integration

**Status:** proposed.

## Objective

Make TinyCC selectable through the Windows JIT runtime infrastructure without changing the default LLVM-MinGW path or the native VS2022 build toolchain, while eliminating shared-file ownership conflicts between compiler packages and centralizing safe activation and cache-identity semantics.

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
- `fenics-jit-runtime` has **no runtime dependency on either compiler backend**;
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
- backend/cache-identity-specific cache-root selection **before FFCx cache lookup**;
- backend lifecycle;
- MPI child-process propagation.

Keep compiler-specific logic isolated:

- LLVM-MinGW: mingw32 backend, Clang/LLD, GNU import libraries, its own cache identity contribution;
- TinyCC: owned direct build_ext adapter, TCC headers/runtime, `.def` imports, `-mms-bitfields`/`long double` ABI policy, strict foreign-binary rejection, system-library policy, qualified CRT/PE-hardening configuration, and its cache identity contribution.

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
  -> fenics-jit-llvm-mingw   # separate dependency selected by DOLFINx/default packaging

fenics-jit-tinycc
  -> fenics-jit-runtime
```

The arrows above are sibling dependencies where shown beneath `fenics-dolfinx`; `fenics-jit-runtime` itself must not depend on `fenics-jit-llvm-mingw`. This is required so a TinyCC-only bundle can contain `fenics-jit-runtime + fenics-jit-tinycc` with LLVM-MinGW absent.

Exact conda metadata may differ if the common runtime is embedded in DOLFINx rather than a separate package; file ownership and backend-neutral dependency direction must remain single-source either way.

Possible final backend policies remain deferred to Phase 7:

1. LLVM-MinGW default, TinyCC optional;
2. TinyCC compact default, LLVM-MinGW fallback;
3. mutually exclusive backend variants;
4. TinyCC rejected and not shipped.

## MPI behavior

The selected backend, backend cache identity, and package root must propagate identically to MPI child processes. A two-rank probe should verify both ranks report the same compiler revision, adapter type, Python ABI definition, include roots, physical cache root, Windows ABI/bitfield policy, system-library policy, and CRT/backend identity.

Do not rely on parent-only monkey patches that are absent in newly launched Python processes.

## Mandatory cache isolation and immutable backend cache identity

LLVM-MinGW and TinyCC must use physically distinct FFCx/CFFI cache namespaces. Different binary-incompatible revisions/configurations of the same backend must also use distinct namespaces. This is a correctness requirement, not an optional optimization.

FFCx 0.11 performs `get_cached_module(...)` before entering CFFI/setuptools compilation. Therefore cache isolation must be resolved in the shared DOLFINx/JIT wrapper **before** calling `ffcx.codegeneration.jit.compile_forms(...)` or `compile_expressions(...)`. Implementing isolation only inside the later compiler/build_ext adapter is too late because a module from another backend or an older incompatible backend revision could already have been loaded.

Each backend package exposes a deterministic identity contribution. The shared runtime derives an immutable `backend-cache-id` that changes whenever generated binary compatibility can change, including at least:

- compiler revision and local patch set;
- adapter/cache-schema version;
- CRT model;
- ABI-affecting flags such as TinyCC `-mms-bitfields`;
- language/optimization policy where binary behavior/compatibility can change;
- Python-link/import-definition policy;
- PE hardening/link policy.

Use a backend-specific physical cache root, conceptually:

```text
<cache>/ffcx/llvm-mingw/<backend-cache-id>/...
<cache>/ffcx/tinycc/<backend-cache-id>/...
```

Required behavior:

- switching `llvm-mingw -> tinycc` forces at least one TinyCC compilation before TinyCC cache reuse;
- switching `tinycc -> llvm-mingw` likewise forces an LLVM-MinGW compilation in its own namespace;
- changing TinyCC compiler revision, patch set, CRT/ABI policy, adapter cache schema, Python-link policy, or hardening/link policy changes `backend-cache-id` and forces fresh compilation;
- one backend/revision must never load a `.pyd` created by another incompatible backend/revision, even if the FFCx module name/source hash is otherwise identical;
- the backend-specific identity/root is established before any cache existence/ready-file check;
- MPI children inherit the same backend cache identity/root;
- diagnostics record the backend cache identity and resolved cache root for every JIT.

Backend selection/compiler identity does not need to become part of FFCx's source hash when physically distinct identity roots enforce isolation, but the identity must be deterministic and auditable.

## Concurrency validation

Add runtime-level tests that exercise the common lock rather than only the TinyCC adapter in isolation:

- two Python threads performing TinyCC JIT requests concurrently;
- two Python threads performing LLVM-MinGW JIT requests concurrently;
- one TinyCC and one LLVM-MinGW request started concurrently;
- same-thread same-backend nested activation;
- same-thread conflicting-backend nested activation, which must fail deterministically;
- compile failure/exception paths followed by a successful activation to prove restoration;
- cache diagnostics proving each completed JIT used the intended backend/cache identity/root.

The expected policy is serialized in-process compilation, not parallel mutation of process-global CFFI/setuptools state.

## Tasks

1. Introduce the single-owner backend-neutral common runtime/bootstrap layout and migrate the existing LLVM-MinGW helper without behavior change.
2. Update DOLFINx's Windows bootstrap to load the common runtime component with backend-neutral diagnostics.
3. Introduce explicit backend selection.
4. Move activation serialization/nesting into the shared runtime and preserve the Phase-2 TinyCC semantics.
5. Factor shared environment/Python/FFCx discovery only where useful.
6. Keep LLVM-MinGW behavior unchanged under the default selector.
7. Add TinyCC backend-root discovery and owned direct build_ext activation.
8. Define backend cache identity contributions for both backends and derive immutable `backend-cache-id` values.
9. Implement backend/cache-identity-specific physical cache roots before FFCx `compile_forms`/`compile_expressions` cache lookup.
10. Verify backend switching and identity changes force fresh compile before same-identity cache reuse.
11. Verify thread concurrency and same/conflicting nested activation semantics across both backends.
12. Verify MPI child-process selection and cache-identity/root propagation.
13. Add diagnostics showing backend, backend-cache-id, exact compiler revision, Windows ABI/bitfield/`long double` policy, system-library policy, CRT identity, and resolved cache root.
14. Add package-file ownership/dependency tests proving no overlap and proving `fenics-jit-runtime` has no compiler-backend dependency.
15. Add regression tests proving LLVM-MinGW remains unchanged.

## Exit criteria

Phase 4 passes when the same DOLFINx/FFCx caller can select LLVM-MinGW or TinyCC deterministically; common runtime files have exactly one owner and no backend dependency; compiler packages install into non-overlapping backend roots; all temporary process-global JIT state is serialized through a single restoration-safe reentrant activation mechanism; conflicting nested backends fail clearly; each backend/binary-incompatible revision uses a physically distinct immutable cache-identity namespace established before FFCx's cache lookup with demonstrated fresh compilation after a switch or identity change; MPI children inherit the choice/cache identity/root; TinyCC-only operation does not depend on LLVM-MinGW for shared runtime code; and installing/testing TinyCC does not change the default backend.
