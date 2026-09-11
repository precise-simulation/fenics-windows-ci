# Phase 3: implement the owned TinyCC CFFI adapter

**Status:** proposed.

## Objective

Integrate TinyCC with CFFI/setuptools through the narrowest maintainable backend while preserving the existing hermetic runtime setup model.

The preferred design is an owned `distutils.ccompiler.CCompiler` implementation plus the smallest owned `build_ext` specialization required to suppress native-Windows setuptools link behavior. Do not use global monkey-patching or pretend TinyCC is MinGW GCC/Clang.

## Adapter responsibilities

Implement only the subset required by CFFI `build_ext`:

- create output directories deterministically;
- compile generated `.c` sources with TinyCC;
- pass include directories and preprocessor definitions;
- produce TCC-compatible intermediate objects when required;
- link those objects into `.pyd` with `tcc -shared`;
- include `python3.def` and any explicitly required system definitions;
- propagate supported extra compile/link flags;
- reject unsupported flags with a clear error;
- emit full command diagnostics when requested.

The adapter must not expose a general-purpose cross-compiler surface unless CFFI actually requires it.

## Integration point

Extend the runtime-helper pattern currently used for LLVM-MinGW. Preferred structure:

```text
shared runtime selection
  -> llvm-mingw backend
  -> tinycc backend
```

The TinyCC backend should be selected in-process from the temporary CFFI `Distribution` and registered only for the duration of the JIT operation.

For the current setuptools/distutils model:

1. import the owned `TinyCCCompiler` subclass inside the activation context before `build_ext` invokes `new_compiler("tinycc")`, so `compiler_type = "tinycc"` is discoverable without persistent registration;
2. install an owned temporary `build_ext` command class for the CFFI `Distribution`;
3. set its compiler explicitly to `tinycc`;
4. restore all replaced classes/process state when activation exits.

The owned `build_ext` layer is required because compiler selection alone does not suppress native-Windows setuptools behavior. It must:

- override Python-library selection so `python312`, `python313`, `python314`, or another minor-version library is never added implicitly;
- reject a versioned Python library if one arrives through extension metadata;
- prevent default Windows `libs`/`PCbuild`/MSVC library-directory injection from participating in the TinyCC link, retaining only explicitly approved runtime/package roots;
- keep the extension export-symbol behavior needed for `PyInit_<module>`;
- define/pass `Py_NO_LINK_LIB` where supported and verify CPython headers do not add an autolink Python dependency;
- pass packaged `python3.def` explicitly to TinyCC.

Avoid:

- persistent changes to setuptools/distutils compiler tables;
- user/global `setup.cfg` dependencies;
- registry compiler discovery;
- shell activation;
- replacing Python's global build compiler settings.

## CFFI/setuptools compatibility contract

CFFI's `_shimmed_dist_utils.Distribution` and setuptools' vendored distutils compiler discovery are private/version-sensitive integration points. Treat them as qualified dependencies rather than assumed stable APIs.

Tests must record the `cffi` and `setuptools` versions and prove for every supported pair that:

- CFFI creates the expected temporary `Distribution` path used by the runtime helper;
- the owned TinyCC compiler subclass is resolved by `new_compiler("tinycc")`;
- the owned `build_ext` command is actually used;
- no alternate compiler/backend is selected;
- the Stable-ABI library suppression remains effective.

Start with the versions in the qualified runtime environment. Any broader package version range must be justified by CI coverage; unsupported combinations fail clearly rather than falling through to ambient/default compilation.

## Flag translation

Create an explicit translation/rejection layer.

Examples:

- `-std:c17` -> a verified TinyCC standard mode or removal if the pinned compiler's default semantics are the validated choice;
- retain `-D__STDC_NO_COMPLEX__` initially;
- add `-DPy_NO_LINK_LIB` where supported;
- convert include/define options directly;
- reject LLVM/GNU linker-map or dependency-generation flags that TinyCC does not support unless an equivalent is implemented;
- keep optimization settings explicit rather than relying on ambient defaults.

Do not silently discard flags that affect ABI, visibility, symbol export, standard semantics, optimization, or Python-library selection.

## Symbol export/import handling

Prove how the CFFI `PyInit_<module>` symbol is exported from the generated PE DLL. Prefer normal generated-source annotations if TinyCC honors them. Otherwise generate a minimal module `.def` file deterministically from the known module init symbol.

Python API imports must come from packaged `python3.def`. The TinyCC link command and resulting PE must contain no minor-version Python dependency.

## Diagnostics

Capture per JIT:

- TinyCC exact revision/version;
- `cffi` and `setuptools` versions;
- selected compiler type and owned build_ext class;
- full compile and link command lines;
- include and library search roots;
- `.def` files used;
- generated `.pyd` import/export table;
- compiler exit output;
- adapter-selected standard/optimization flags.

CI diagnostics should make it impossible to confuse a TinyCC build with LLVM-MinGW/MSVC fallback or to miss an implicit `pythonXY` link input.

## Tasks

1. Implement a private TinyCC `CCompiler` subclass.
2. Implement the temporary owned `build_ext` specialization for Stable-ABI/library-root control.
3. Register/select both only inside the owned runtime activation context.
4. Implement compile/link option translation.
5. Implement deterministic `.def` handling for Python imports and, if needed, extension exports.
6. Add tests for paths with spaces and non-default temporary directories.
7. Add negative tests proving unsupported important flags and versioned Python libraries fail loudly.
8. Add CFFI/setuptools compatibility tests for the package-supported version range.
9. Add diagnostics and PE verification.
10. Ensure runtime activation restores all process state after JIT.

## Exit criteria

Phase 3 passes when unmodified CFFI/FFCx callers can compile through the TinyCC backend without global configuration, the TinyCC compiler and owned build_ext path are selected deterministically for the declared CFFI/setuptools versions, no host compiler or implicit versioned Python library can be selected accidentally, and the adapter is small enough to review as a dedicated FEniCS Windows integration layer.
