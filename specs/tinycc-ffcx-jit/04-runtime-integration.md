# Phase 4: private qualification, then single-owner runtime integration

**Status:** proposed.

## Objective

Avoid restructuring the qualified LLVM-MinGW production runtime for an experimental backend until the packaged TinyCC path has survived a broad private qualification gate. Phase 4 is deliberately split:

- **Phase 4A — private TinyCC qualification:** exercise the installed Phase-3 TinyCC backend broadly through its private activation/cache path, without modifying the production DOLFINx bootstrap, LLVM-MinGW runtime ownership, or default dependency shape.
- **Phase 4B — shared-runtime integration:** only after Phase 4A passes, make TinyCC selectable through the Windows JIT runtime infrastructure, introduce single-owner common runtime files, and qualify side-by-side backend/cache/concurrency behavior.

The native VS2022 build toolchain remains unchanged throughout.

## Phase 4A: private TinyCC qualification gate

Phase 4A exists to catch backend-specific failures before production runtime/package architecture is changed.

Use the installed Phase-3 `fenics-jit-tinycc` package and its private activation entry point. Do **not** yet:

- change the DOLFINx Windows bootstrap;
- split the existing LLVM-MinGW runtime/helper ownership;
- change `fenics-dolfinx` dependencies;
- introduce a production backend selector;
- modify the LLVM-MinGW default path merely to exercise TinyCC.

Run, at minimum, the TinyCC-specific portions of the later broad validation matrix that do not require shared cross-backend infrastructure:

- standard GIL-enabled CPython 3.12, 3.13, and 3.14;
- scalar, vector/tensor, cell/facet, coefficient-heavy, and representative higher-order forms;
- fresh JIT and private TinyCC cache reload;
- numerical comparison with the LLVM-MinGW reference outputs/tolerances;
- paths containing spaces and non-default temporary directories;
- repeated same-process and new-process TinyCC compile/load cycles;
- ABI/packing/bitfield/`long double` regression probes;
- Stable-ABI Python-link checks;
- CRT/allocator ownership stress identified by Phases 1-2;
- PE mitigation/relocation/unwind inspection;
- system-library provenance checks;
- foreign-object/library negative cases;
- hostile external setuptools/distutils configuration proving the owned CFFI `Distribution` interception remains hermetic.

Python 3.15 preview may be collected as non-blocking evidence but is not part of the Phase-4A pass/fail gate until it is a supported repository runtime.

MPI cases that require child-process backend propagation, cross-backend cache switching, and TinyCC-vs-LLVM concurrency are deferred to Phase 4B/5 because those require the shared runtime architecture.

### Phase 4A exit gate

Do not begin production shared-runtime refactoring unless Phase 4A demonstrates that the packaged TinyCC backend is viable across the broad private matrix. If Phase 4A rejects TinyCC for generated-C, numerical, ABI/CRT, PE-security, hermeticity, or stability reasons, stop the epic without restructuring the qualified LLVM-MinGW runtime.

## Phase 4B: runtime ownership split

After Phase 4A passes, factor common JIT lifecycle/selection code into one uniquely owned runtime component, provisionally:

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
- TinyCC: owned CFFI `Distribution` interception/direct build_ext adapter, TCC headers/runtime, `.def` imports, external-config suppression, `-mms-bitfields`/`long double` ABI policy, strict foreign-binary rejection, system-library policy, qualified CRT/PE-hardening configuration, and its cache identity contribution.

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

Do not replace the existing `fenics-dolfinx -> fenics-jit-llvm-mingw` runtime dependency before Phase 4A passes and the Phase-4B shared-runtime split is implemented and qualified.

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

The selected backend, backend cache identity, and package root must propagate identically to MPI child processes. A two-rank probe should verify both ranks report the same compiler revision, adapter type, Python ABI definition, include roots, physical cache root, Windows ABI/bitfield policy, system-library policy, CRT/backend identity, and external-config policy.

Do not rely on parent-only monkey patches that are absent in newly launched Python processes.

## Mandatory cache isolation and immutable backend cache identity

LLVM-MinGW and TinyCC must use physically distinct FFCx/CFFI cache namespaces. Different binary-incompatible revisions/configurations of the same backend must also use distinct namespaces. This is a correctness requirement, not an optional optimization.

FFCx 0.11 performs `get_cached_module(...)` before entering CFFI/setuptools compilation. Therefore cache isolation must be resolved in the shared DOLFINx/JIT wrapper **before** calling `ffcx.codegeneration.jit.compile_forms(...)` or `compile_expressions(...)`. Implementing isolation only inside the later compiler/build_ext adapter is too late because a module from another backend or an older incompatible backend revision could already have been loaded.

Each backend package exposes a deterministic identity contribution. The shared runtime derives an immutable `backend-cache-id` that changes whenever generated binary compatibility can change, including at least:

- compiler revision and local patch set;
- adapter/cache-schema and external-config-policy version;
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
- changing TinyCC compiler revision, patch set, CRT/ABI policy, adapter cache schema, external-config policy, Python-link policy, or hardening/link policy changes `backend-cache-id` and forces fresh compilation;
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

### Phase 4A

1. Run the broad private TinyCC qualification matrix from the installed Phase-3 package without changing production LLVM-MinGW runtime ownership/bootstrap/dependencies.
2. Preserve generated-source, command, numerical, ABI/CRT, PE, hermeticity, and hostile-config evidence.
3. Record an explicit Phase-4A pass/reject decision before any Phase-4B production refactor starts.

### Phase 4B

4. Introduce the single-owner backend-neutral common runtime/bootstrap layout and migrate the existing LLVM-MinGW helper without behavior change.
5. Update DOLFINx's Windows bootstrap to load the common runtime component with backend-neutral diagnostics.
6. Introduce explicit backend selection.
7. Move activation serialization/nesting into the shared runtime and preserve the Phase-2 TinyCC semantics.
8. Factor shared environment/Python/FFCx discovery only where useful.
9. Keep LLVM-MinGW behavior unchanged under the default selector.
10. Add TinyCC backend-root discovery and owned direct build_ext activation.
11. Define backend cache identity contributions for both backends and derive immutable `backend-cache-id` values.
12. Implement backend/cache-identity-specific physical cache roots before FFCx `compile_forms`/`compile_expressions` cache lookup.
13. Verify backend switching and identity changes force fresh compile before same-identity cache reuse.
14. Verify thread concurrency and same/conflicting nested activation semantics across both backends.
15. Verify MPI child-process selection and cache-identity/root propagation.
16. Add diagnostics showing backend, backend-cache-id, exact compiler revision, Windows ABI/bitfield/`long double` policy, external-config policy, system-library policy, CRT identity, and resolved cache root.
17. Add package-file ownership/dependency tests proving no overlap and proving `fenics-jit-runtime` has no compiler-backend dependency.
18. Add regression tests proving LLVM-MinGW remains unchanged.

## Exit criteria

Phase 4A passes only when the installed TinyCC package survives the broad private qualification gate without changing the production LLVM-MinGW runtime architecture. Phase 4B begins only after that result is recorded.

Phase 4 is complete when the same DOLFINx/FFCx caller can select LLVM-MinGW or TinyCC deterministically; common runtime files have exactly one owner and no backend dependency; compiler packages install into non-overlapping backend roots; all temporary process-global JIT state is serialized through a single restoration-safe reentrant activation mechanism; conflicting nested backends fail clearly; each backend/binary-incompatible revision uses a physically distinct immutable cache-identity namespace established before FFCx's cache lookup with demonstrated fresh compilation after a switch or identity change; MPI children inherit the choice/cache identity/root; TinyCC-only operation does not depend on LLVM-MinGW for shared runtime code; and installing/testing TinyCC does not change the default backend.
