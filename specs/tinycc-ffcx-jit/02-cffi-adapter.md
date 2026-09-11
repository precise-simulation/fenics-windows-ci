# Phase 2: implement the owned TinyCC CFFI adapter

**Status:** proposed.

## Objective

Turn the Phase 1 prototype into the production TinyCC CFFI/setuptools backend through the narrowest maintainable integration while preserving the existing hermetic runtime setup model.

The preferred design is an owned temporary `build_ext` specialization whose `build_extension()` validates the CFFI `Extension` metadata and invokes TinyCC directly from generated C source to the final `.pyd`. Do not use global compiler configuration, do not pretend TinyCC is MinGW GCC/Clang, and do not build a general-purpose distutils `CCompiler` abstraction unless qualification proves the direct path is insufficient.

Phase 2 completes the production adapter before Phase 3 packages it as `fenics-jit-tinycc`.

## Why direct build_ext is preferred

CFFI's current out-of-line build path creates a temporary `Distribution`, runs its `build_ext` command, then consumes the command output path. FFCx supplies generated C source and does not require a reusable Windows object-file API.

Therefore the production path should be:

```text
CFFI Extension
  -> TinyCCBuildExt.build_extension(ext)
  -> validate/translate extension metadata
  -> tcc -shared <generated sources> <approved definitions> ... -o <module.pyd>
  -> record get_outputs()/diagnostics
```

This deliberately avoids TinyCC's Windows `-c` ELF intermediates. If a future qualified CFFI/setuptools combination demonstrably requires the normal compiler-object split, introduce the smallest private compiler object needed at that time; do not pre-commit the architecture to a broader compiler API.

## Adapter responsibilities

Implement only the subset required by CFFI `build_ext`:

- determine the exact extension output path expected by setuptools/CFFI;
- create output directories deterministically;
- consume generated `.c` sources directly;
- pass approved include directories and preprocessor definitions;
- invoke `tcc -shared` to produce the final `.pyd`;
- include `python3.def` and any explicitly qualified system-import inputs;
- translate supported compile/link flags;
- reject unsupported flags, source types, libraries, library directories, and binary inputs with a clear error;
- preserve the extension output/reporting contract (`get_outputs()` and expected file placement);
- emit full command diagnostics when requested.

TinyCC's Windows `-c` path emits ELF objects. The adapter must not expose those intermediates as general-purpose Windows object files or imply normal COFF interchange compatibility.

## Integration point

Extend the runtime-helper pattern currently used for LLVM-MinGW. Phase 4 will supply the common runtime selector; Phase 2 focuses on a production backend object that can be activated by that selector.

For the current CFFI/setuptools model:

1. install an owned temporary `build_ext` command class for the CFFI `Distribution`;
2. override `build_extension()` to validate the `Extension` and invoke TinyCC directly;
3. override/supply output-path bookkeeping required by CFFI/setuptools;
4. provide only include/library/definition inputs approved for the TinyCC backend;
5. restore all replaced command/distribution/process state when activation exits.

Only if this path cannot satisfy a qualified setuptools/CFFI version may the adapter introduce a private compiler implementation or `new_compiler()` integration. Any fallback must acknowledge that imported compiler subclasses can remain discoverable process-wide; selection and configuration, not class existence, must be the process-local property.

The owned `build_ext` layer must:

- override Python-library selection so `python312`, `python313`, `python314`, or another minor-version library is never added implicitly;
- reject a versioned Python library if one arrives through extension metadata;
- prevent default Windows `libs`/`PCbuild`/MSVC/Windows-SDK library-directory injection from participating in the TinyCC link, retaining only explicitly approved roots;
- keep the extension export-symbol behavior needed for `PyInit_<module>`;
- record `_MSC_VER`, `Py_LIMITED_API`, and `Py_NO_LINK_LIB` behavior for the active CPython headers;
- recognize that CPython pragma autolinking is `_MSC_VER`-conditioned, so command/import inspection is the authoritative Python-link check;
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

CFFI's `_shimmed_dist_utils.Distribution` and setuptools' vendored distutils/build_ext implementation are version-sensitive integration points. Treat them as qualified dependencies rather than assumed stable APIs.

Tests must record the `cffi` and `setuptools` versions and prove for every supported pair that:

- CFFI creates the expected temporary `Distribution` path used by the runtime helper;
- the owned TinyCC `build_ext` command is actually used;
- its `build_extension()` receives the generated CFFI `Extension` and produces the output path consumed by CFFI;
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
- add `-DPy_NO_LINK_LIB` only where the active CPython headers support it and record whether `_MSC_VER` makes pragma autolinking relevant;
- convert include/define options directly;
- reject LLVM/GNU linker-map or dependency-generation flags that TinyCC does not support unless an equivalent is implemented;
- keep optimization settings explicit rather than relying on ambient defaults;
- encode the Phase-1-qualified PE mitigation options explicitly.

Do not silently discard flags that affect ABI, packing/bitfields, visibility, symbol export, standard semantics, optimization, Python-library selection, CRT selection, or PE hardening.

The adapter must also preserve the Phase-1 `long double` contract: no incompatible `long double` representation may cross into MSVC/UCRT-built UFCx/DOLFINx interfaces.

## Object/library input contract

TinyCC's Windows object model is not a normal MSVC/MinGW COFF interchange surface. Direct source-to-PYD compilation is the default, and the adapter must have a narrow allowlist.

Allowed inputs:

- generated C sources;
- explicitly packaged/approved `.def` imports such as `python3.def` and qualified system definitions;
- approved Windows system-DLL resolution only if Phase 1 selected that policy;
- TCC-owned intermediate objects/archives only if a qualified fallback path proves they are necessary.

Reject before invoking TinyCC:

- MSVC `.lib` libraries;
- foreign `.obj`/`.o` files;
- arbitrary `.a` archives;
- `extra_objects` unless a qualified fallback explicitly owns and verifies them;
- arbitrary `cffi_libraries` names that are not mapped to an approved import mechanism;
- host SDK/Python/MSVC library directories;
- non-C source files not explicitly supported by the backend.

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

The adapter must make the Phase-1-qualified CRT and fixed x64 PE-hardening choices explicit rather than relying on TinyCC defaults that can change with an upstream update.

Use supported TinyCC linker controls and require the Phase-1 baseline:

- `DYNAMIC_BASE`;
- `HIGH_ENTROPY_VA`;
- `NX_COMPAT`;
- usable base relocations;
- qualified x64 unwind/exception metadata.

A source patch is backend identity only if Phase 1 demonstrated that supported controls were insufficient.

Per JIT, verify/record as applicable:

- selected CRT/system definition or system-DLL inputs;
- resulting CRT/system imports;
- `DllCharacteristics` mitigation bits;
- relocation/unwind metadata presence expected by the qualified backend.

Any backend source patch/configuration required for those properties is part of the pinned TinyCC backend identity and therefore part of the backend cache identity.

## Backend cache identity contribution

The adapter/package metadata must expose a deterministic identity contribution covering compiler and binary-generation policy, including compiler revision/patch set, adapter cache-schema version, CRT model, ABI flags, Python-link policy, and PE hardening/link policy.

Phase 4 combines this with the backend name to select a physical FFCx cache root **before** FFCx cache lookup. Do not attempt to solve cache isolation solely inside `build_extension()`; by then FFCx may already have loaded a cached module.

## Diagnostics

Capture per JIT:

- TinyCC exact revision/version and local patch identity;
- backend cache identity;
- `cffi` and `setuptools` versions;
- selected owned build_ext implementation;
- activation owner/backend and lock/nesting diagnostics when verbose mode is enabled;
- full TinyCC command line;
- source files and approved include/definition/library search roots;
- `.def` files used;
- `_MSC_VER`, `Py_LIMITED_API`, and `Py_NO_LINK_LIB` state;
- effective bitfield/packing and `long double` policy;
- approved system-library policy and resolved imports;
- generated `.pyd` import/export table and mitigation characteristics;
- compiler exit output;
- adapter-selected standard/optimization/hardening flags;
- backend-specific physical cache root supplied by the shared runtime.

CI diagnostics should make it impossible to confuse a TinyCC build with LLVM-MinGW/MSVC fallback, to miss an implicit `pythonXY` link input, to miss a foreign binary input, or to miss an activation-state race.

## Tasks

1. Implement the production private TinyCC `build_ext` command with direct source-to-PYD `build_extension()`.
2. Implement deterministic output-path/reporting behavior expected by CFFI/setuptools.
3. Implement the process-wide reentrant activation lock and nested/conflicting-backend semantics.
4. Implement compile/link option translation for the Phase-1-qualified TinyCC language and Windows ABI mode, including `-mms-bitfields` policy.
5. Implement deterministic `.def` handling for Python imports and, if needed, extension exports.
6. Implement the Phase-1-qualified system-library-resolution policy.
7. Implement the strict source/object/library allowlist and negative tests.
8. Add tests for paths with spaces and non-default temporary directories.
9. Add negative tests proving unsupported important flags and versioned Python libraries fail loudly.
10. Add concurrency/nesting/restoration tests for same-backend and conflicting-backend activation.
11. Add CFFI/setuptools compatibility tests for the package-supported version range.
12. Add diagnostics plus PE/CRT/import/cache-identity verification hooks.
13. Ensure runtime activation restores all temporary Distribution/build_ext/CFFI/environment state after JIT success or failure.
14. Only if the direct build_ext path fails a demonstrated CFFI requirement, document that evidence and introduce the smallest private compiler fallback necessary.

## Exit criteria

Phase 2 passes when unmodified CFFI/FFCx callers compile through the direct TinyCC build_ext path without global compiler configuration; the owned command is selected deterministically for the declared CFFI/setuptools versions; temporary process-global state is serialized and restoration-safe; the Windows bitfield/packing/`long double`, Python-link, CRT, fixed PE-hardening, system-library, object-input, and backend-cache-identity contracts from Phase 1 are explicit; no host compiler, implicit versioned Python library, or unsupported foreign binary input can be selected accidentally; and the adapter remains a narrow FEniCS Windows integration layer rather than a general-purpose TinyCC distutils backend.
