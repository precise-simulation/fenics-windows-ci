# Phase 3: implement the owned TinyCC CFFI adapter

**Status:** proposed.

## Objective

Integrate TinyCC with CFFI/setuptools through the narrowest maintainable backend while preserving the existing hermetic runtime setup model.

The preferred design is an owned temporary `build_ext` specialization that directly instantiates a private TinyCC compiler implementation. Do not use global monkey-patching, do not pretend TinyCC is MinGW GCC/Clang, and do not depend on the claim that importing a compiler subclass can be temporarily registered/unregistered.

## Adapter responsibilities

Implement only the subset required by CFFI `build_ext`:

- create output directories deterministically;
- compile generated `.c` sources with TinyCC;
- pass include directories and preprocessor definitions;
- produce TCC-compatible intermediate objects when required;
- link those objects into `.pyd` with `tcc -shared`;
- include `python3.def` and any explicitly required system definitions;
- propagate supported extra compile/link flags;
- reject unsupported flags and unsupported binary inputs with a clear error;
- emit full command diagnostics when requested.

The adapter must not expose a general-purpose cross-compiler surface unless CFFI actually requires it.

## Integration point

Extend the runtime-helper pattern currently used for LLVM-MinGW. Phase 4 will supply the common runtime selector; Phase 3 focuses on a backend object that can be activated by that selector.

For the current CFFI/setuptools model:

1. install an owned temporary `build_ext` command class for the CFFI `Distribution`;
2. have that command instantiate `TinyCCCompiler` directly rather than calling `new_compiler("tinycc")`;
3. provide only the include/library/definition inputs approved for the TinyCC backend;
4. restore all replaced command/distribution process state when activation exits.

If direct instantiation cannot be made compatible with a qualified setuptools version, a fallback may expose `compiler_type = "tinycc"` for `new_compiler()`, but the design must acknowledge that imported compiler subclasses remain discoverable process-wide. In that fallback, selection and configuration — not class existence — must be the process-local property.

The owned `build_ext` layer must:

- override Python-library selection so `python312`, `python313`, `python314`, or another minor-version library is never added implicitly;
- reject a versioned Python library if one arrives through extension metadata;
- prevent default Windows `libs`/`PCbuild`/MSVC library-directory injection from participating in the TinyCC link, retaining only explicitly approved runtime/package roots;
- keep the extension export-symbol behavior needed for `PyInit_<module>`;
- define/pass `Py_NO_LINK_LIB` where supported and verify CPython headers do not add an autolink Python dependency;
- pass packaged `python3.def` explicitly to TinyCC.

Avoid:

- user/global `setup.cfg` dependencies;
- registry compiler discovery;
- shell activation;
- replacing Python's global build compiler settings;
- relying on class-registration rollback as an isolation mechanism.

## CFFI/setuptools compatibility contract

CFFI's `_shimmed_dist_utils.Distribution` and setuptools' vendored distutils/compiler implementation are version-sensitive integration points. Treat them as qualified dependencies rather than assumed stable APIs.

Tests must record the `cffi` and `setuptools` versions and prove for every supported pair that:

- CFFI creates the expected temporary `Distribution` path used by the runtime helper;
- the owned TinyCC `build_ext` command is actually used;
- the owned command directly creates the TinyCC compiler implementation, or the explicitly qualified fallback discovery path is used;
- no alternate compiler/backend is selected;
- the Stable-ABI library suppression remains effective.

Start with the versions in the qualified runtime environment. Any broader package version range must be justified by CI coverage; unsupported combinations fail clearly rather than falling through to ambient/default compilation.

## Flag translation

Create an explicit translation/rejection layer.

Examples:

- `-std:c17` -> the verified TinyCC C11/default mode selected by Phase 1; do not imply TinyCC has a native C17 mode;
- retain `-D__STDC_NO_COMPLEX__` initially;
- add `-DPy_NO_LINK_LIB` only where the active CPython headers support it;
- convert include/define options directly;
- reject LLVM/GNU linker-map or dependency-generation flags that TinyCC does not support unless an equivalent is implemented;
- keep optimization settings explicit rather than relying on ambient defaults.

Do not silently discard flags that affect ABI, visibility, symbol export, standard semantics, optimization, Python-library selection, or PE hardening.

## Object/library input contract

TinyCC's Windows object model is not a normal MSVC/MinGW COFF interchange surface. The adapter must have a narrow allowlist.

Allowed inputs:

- generated C sources;
- TCC-owned intermediate objects/archives created by the same qualified backend;
- explicitly packaged/approved `.def` imports such as `python3.def` and required system definitions.

Reject before invoking TinyCC:

- MSVC `.lib` libraries;
- foreign `.obj`/`.o` files;
- arbitrary `.a` archives;
- `extra_objects` unless they are explicitly tagged/verified as TCC-owned inputs;
- arbitrary `cffi_libraries` names that are not mapped to approved packaged `.def` imports.

Diagnostics must identify the rejected source of the input so future FFCx/CFFI changes fail clearly rather than producing confusing linker behavior.

## Symbol export/import handling

Prove how the CFFI `PyInit_<module>` symbol is exported from the generated PE DLL. Prefer normal generated-source annotations if TinyCC honors them. Otherwise generate a minimal module `.def` file deterministically from the known module init symbol.

Python API imports must come from packaged `python3.def`. The TinyCC link command and resulting PE must contain no minor-version Python dependency.

## CRT and PE properties

The adapter must make the Phase-1-qualified CRT and PE-hardening choices explicit rather than relying on TinyCC defaults that can change with an upstream update.

Per JIT, verify/record as applicable:

- selected CRT/system definition inputs;
- resulting CRT/system imports;
- `DllCharacteristics` mitigation bits;
- relocation/unwind metadata presence expected by the qualified backend.

Any backend source patch/configuration required for those properties is part of the pinned TinyCC backend identity.

## Diagnostics

Capture per JIT:

- TinyCC exact revision/version and local patch identity;
- `cffi` and `setuptools` versions;
- selected owned build_ext/compiler implementation;
- full compile and link command lines;
- include and approved definition/library search roots;
- `.def` files used;
- generated `.pyd` import/export table and mitigation characteristics;
- compiler exit output;
- adapter-selected standard/optimization flags;
- backend-specific cache root supplied by the shared runtime.

CI diagnostics should make it impossible to confuse a TinyCC build with LLVM-MinGW/MSVC fallback, to miss an implicit `pythonXY` link input, or to miss a foreign binary input.

## Tasks

1. Implement a private TinyCC compiler class/implementation.
2. Implement the temporary owned `build_ext` specialization that directly instantiates it.
3. Implement compile/link option translation for the Phase-1-qualified TinyCC language mode.
4. Implement deterministic `.def` handling for Python imports and, if needed, extension exports.
5. Implement the strict object/library allowlist and negative tests.
6. Add tests for paths with spaces and non-default temporary directories.
7. Add negative tests proving unsupported important flags and versioned Python libraries fail loudly.
8. Add CFFI/setuptools compatibility tests for the package-supported version range.
9. Add diagnostics plus PE/CRT verification hooks.
10. Ensure runtime activation restores all temporary Distribution/build_ext/process state after JIT.

## Exit criteria

Phase 3 passes when unmodified CFFI/FFCx callers can compile through the TinyCC backend without global configuration; the owned build_ext/compiler path is selected deterministically for the declared CFFI/setuptools versions; no host compiler, implicit versioned Python library, or unsupported foreign binary input can be selected accidentally; the qualified CRT/PE properties remain explicit; and the adapter is small enough to review as a dedicated FEniCS Windows integration layer.
