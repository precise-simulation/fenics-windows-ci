# Phase 2: implement the owned TinyCC CFFI adapter

**Status:** proposed.

## Objective

Turn the Phase 1 prototype into the production TinyCC CFFI/setuptools backend through the narrowest maintainable integration while preserving the existing hermetic runtime setup model.

The preferred design is an owned temporary `build_ext` specialization that directly instantiates a private TinyCC compiler implementation. Do not use global compiler configuration, do not pretend TinyCC is MinGW GCC/Clang, and do not depend on the claim that importing a compiler subclass can be temporarily registered/unregistered.

Phase 2 completes the production adapter before Phase 3 packages it as `fenics-jit-tinycc`.

## Adapter responsibilities

Implement only the subset required by CFFI `build_ext`:

- create output directories deterministically;
- compile generated `.c` sources with TinyCC;
- pass include directories and preprocessor definitions;
- use TCC-owned intermediate objects only where the CFFI/build_ext contract requires them;
- link those sources/objects into `.pyd` with `tcc -shared`;
- include `python3.def` and any explicitly qualified system-import inputs;
- propagate supported extra compile/link flags;
- reject unsupported flags and unsupported binary inputs with a clear error;
- emit full command diagnostics when requested.

TinyCC's Windows `-c` path emits ELF objects. The adapter must not expose those intermediates as general-purpose Windows object files or imply normal COFF interchange compatibility.

The adapter must not expose a general-purpose cross-compiler surface unless CFFI actually requires it.

## Integration point

Extend the runtime-helper pattern currently used for LLVM-MinGW. Phase 4 will supply the common runtime selector; Phase 2 focuses on a production backend object that can be activated by that selector.

For the current CFFI/setuptools model:

1. install an owned temporary `build_ext` command class for the CFFI `Distribution`;
2. have that command instantiate `TinyCCCompiler` directly rather than calling `new_compiler("tinycc")`;
3. provide only the include/library/definition inputs approved for the TinyCC backend;
4. restore all replaced command/distribution/process state when activation exits.

If direct instantiation cannot be made compatible with a qualified setuptools version, a fallback may expose `compiler_type = "tinycc"` for `new_compiler()`, but the design must acknowledge that imported compiler subclasses remain discoverable process-wide. In that fallback, selection and configuration — not class existence — must be the process-local property.

The owned `build_ext` layer must:

- override Python-library selection so `python312`, `python313`, `python314`, or another minor-version library is never added implicitly;
- reject a versioned Python library if one arrives through extension metadata;
- prevent default Windows `libs`/`PCbuild`/MSVC/Windows-SDK library-directory injection from participating in the TinyCC link, retaining only explicitly approved roots;
- keep the extension export-symbol behavior needed for `PyInit_<module>`;
- define/pass `Py_NO_LINK_LIB` only where the active CPython headers support it;
- independently verify that no CPython header-driven Python dependency appears on every supported version, including versions where `Py_NO_LINK_LIB` is unavailable;
- pass the Stable-ABI `python3.def` explicitly to TinyCC.

Avoid:

- user/global `setup.cfg` dependencies;
- registry compiler discovery;
- shell activation;
- replacing Python's global build compiler settings;
- relying on class-registration rollback as an isolation mechanism.

## Activation and concurrency contract

CFFI/setuptools integration may require temporary process-global mutations, including environment variables, the shim `Distribution`, command classes, or narrowly scoped CFFI hooks. Those mutations must not be concurrently observable by another JIT activation.

Implement a process-wide reentrant activation lock with these semantics:

- one JIT activation owns all temporary process-global compiler-selection state until restoration completes;
- same-thread/same-backend nested activation is permitted and reference-counted or otherwise proven restoration-safe;
- conflicting nested activation for a different backend fails immediately with a clear error rather than switching process-global compiler state underneath an active JIT;
- another thread attempting activation waits for the active owner rather than interleaving mutations;
- restoration occurs in `finally` paths for success and failure;
- subprocess compilation may occur while the lock is held; correctness takes priority over same-process parallel JIT compilation.

Free-threaded Python remains outside this epic, but standard GIL-enabled CPython does not remove the need for this lock because Python threads can interleave around subprocess and I/O operations.

Add tests for:

- two threads requesting TinyCC JIT concurrently;
- same-thread nested TinyCC activation;
- TinyCC activation nested under or racing LLVM-MinGW activation;
- exception paths that must restore the previous environment/hooks.

## CFFI/setuptools compatibility contract

CFFI's `_shimmed_dist_utils.Distribution` and setuptools' vendored distutils/compiler implementation are version-sensitive integration points. Treat them as qualified dependencies rather than assumed stable APIs.

Tests must record the `cffi` and `setuptools` versions and prove for every supported pair that:

- CFFI creates the expected temporary `Distribution` path used by the runtime helper;
- the owned TinyCC `build_ext` command is actually used;
- the owned command directly creates the TinyCC compiler implementation, or the explicitly qualified fallback discovery path is used;
- no alternate compiler/backend is selected;
- Stable-ABI library suppression remains effective;
- activation locking/restoration remains correct.

Start with the versions in the qualified runtime environment. Any broader package version range must be justified by CI coverage; unsupported combinations fail clearly rather than falling through to ambient/default compilation.

## Flag translation and Windows ABI policy

Create an explicit translation/rejection layer.

Examples:

- `-std:c17` -> the verified TinyCC C11/default mode selected by Phase 1; do not imply TinyCC has a native C17 mode;
- retain `-D__STDC_NO_COMPLEX__` initially;
- require `-mms-bitfields` for Windows unless Phase 1's ABI record explicitly proves that no supported cross-compiler ABI surface requires MS bitfield layout;
- add `-DPy_NO_LINK_LIB` only where the active CPython headers support it;
- convert include/define options directly;
- reject LLVM/GNU linker-map or dependency-generation flags that TinyCC does not support unless an equivalent is implemented;
- keep optimization settings explicit rather than relying on ambient defaults;
- encode the Phase-1-qualified PE mitigation options explicitly.

Do not silently discard flags that affect ABI, packing/bitfields, visibility, symbol export, standard semantics, optimization, Python-library selection, CRT selection, or PE hardening.

## Object/library input contract

TinyCC's Windows object model is not a normal MSVC/MinGW COFF interchange surface. The adapter must have a narrow allowlist.

Allowed inputs:

- generated C sources;
- TCC-owned intermediate objects/archives created by the same qualified backend where required;
- explicitly packaged/approved `.def` imports such as `python3.def` and qualified system definitions;
- approved Windows system-DLL resolution only if Phase 1 selected that policy.

Reject before invoking TinyCC:

- MSVC `.lib` libraries;
- foreign `.obj`/`.o` files;
- arbitrary `.a` archives;
- `extra_objects` unless they are explicitly tagged/verified as TCC-owned inputs;
- arbitrary `cffi_libraries` names that are not mapped to an approved import mechanism;
- host SDK/Python/MSVC library directories.

Diagnostics must identify the rejected source of the input so future FFCx/CFFI changes fail clearly rather than producing confusing linker behavior.

## System-library resolution

Encode the Phase-1 decision explicitly in the adapter rather than inheriting TinyCC defaults silently.

If normal Windows system-DLL lookup is approved:

- allow only the qualified Windows system directory roots;
- keep host Windows SDK development/import-library directories excluded;
- record the approved roots and resulting PE imports;
- fail if an unexpected non-system ambient library root participates.

If fully explicit `.def` inputs are selected instead, configure TinyCC so implicit library search cannot re-enter through defaults and package all required approved definitions.

Either policy must be testable and represented in backend metadata.

## Symbol export/import handling

Prove how the CFFI `PyInit_<module>` symbol is exported from the generated PE DLL. Prefer normal generated-source annotations if TinyCC honors them. Otherwise generate a minimal module `.def` file deterministically from the known module-init symbol.

Python API imports must come from packaged `python3.def`. The TinyCC link command and resulting PE must contain no minor-version Python dependency.

## CRT and PE properties

The adapter must make the Phase-1-qualified CRT and PE-hardening choices explicit rather than relying on TinyCC defaults that can change with an upstream update.

Use supported TinyCC linker controls for dynamic base, high-entropy VA, and NX compatibility when those controls satisfied Phase 1. A source patch is backend identity only if Phase 1 demonstrated that supported controls were insufficient.

Per JIT, verify/record as applicable:

- selected CRT/system definition or system-DLL inputs;
- resulting CRT/system imports;
- `DllCharacteristics` mitigation bits;
- relocation/unwind metadata presence expected by the qualified backend.

Any backend source patch/configuration required for those properties is part of the pinned TinyCC backend identity.

## Diagnostics

Capture per JIT:

- TinyCC exact revision/version and local patch identity;
- `cffi` and `setuptools` versions;
- selected owned build_ext/compiler implementation;
- activation owner/backend and lock/nesting diagnostics when verbose mode is enabled;
- full compile and link command lines;
- include and approved definition/library search roots;
- `.def` files used;
- whether `Py_NO_LINK_LIB` was available/used;
- effective bitfield/packing policy;
- approved system-library policy and resolved imports;
- generated `.pyd` import/export table and mitigation characteristics;
- compiler exit output;
- adapter-selected standard/optimization/hardening flags;
- backend-specific cache root supplied by the shared runtime.

CI diagnostics should make it impossible to confuse a TinyCC build with LLVM-MinGW/MSVC fallback, to miss an implicit `pythonXY` link input, to miss a foreign binary input, or to miss an activation-state race.

## Tasks

1. Implement the production private TinyCC compiler class/implementation.
2. Implement the temporary owned `build_ext` specialization that directly instantiates it.
3. Implement the process-wide reentrant activation lock and nested/conflicting-backend semantics.
4. Implement compile/link option translation for the Phase-1-qualified TinyCC language and Windows ABI mode, including `-mms-bitfields` policy.
5. Implement deterministic `.def` handling for Python imports and, if needed, extension exports.
6. Implement the Phase-1-qualified system-library-resolution policy.
7. Implement the strict object/library allowlist and negative tests.
8. Add tests for paths with spaces and non-default temporary directories.
9. Add negative tests proving unsupported important flags and versioned Python libraries fail loudly.
10. Add concurrency/nesting/restoration tests for same-backend and conflicting-backend activation.
11. Add CFFI/setuptools compatibility tests for the package-supported version range.
12. Add diagnostics plus PE/CRT/import verification hooks.
13. Ensure runtime activation restores all temporary Distribution/build_ext/CFFI/environment state after JIT success or failure.

## Exit criteria

Phase 2 passes when unmodified CFFI/FFCx callers can compile through the TinyCC backend without global configuration; the owned build_ext/compiler path is selected deterministically for the declared CFFI/setuptools versions; temporary process-global state is serialized and restoration-safe; the Windows bitfield/packing, Python-link, CRT, PE-hardening, system-library, and object-input contracts from Phase 1 are explicit; no host compiler, implicit versioned Python library, or unsupported foreign binary input can be selected accidentally; and the adapter is small enough to review as a dedicated FEniCS Windows integration layer.
