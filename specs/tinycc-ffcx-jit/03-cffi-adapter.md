# Phase 3: implement the owned TinyCC CFFI adapter

**Status:** proposed.

## Objective

Integrate TinyCC with CFFI/setuptools through the narrowest maintainable backend while preserving the existing hermetic runtime setup model.

The preferred design is an owned `distutils.ccompiler.CCompiler` implementation rather than global monkey-patching or pretending TinyCC is MinGW GCC/Clang.

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

Avoid:

- persistent changes to setuptools/distutils compiler tables;
- user/global `setup.cfg` dependencies;
- registry compiler discovery;
- shell activation;
- replacing Python's global build compiler settings.

## Flag translation

Create an explicit translation/rejection layer.

Examples:

- `-std:c17` -> a verified TinyCC standard mode or removal if the pinned compiler's default semantics are the validated choice;
- retain `-D__STDC_NO_COMPLEX__` initially;
- convert include/define options directly;
- reject LLVM/GNU linker-map or dependency-generation flags that TinyCC does not support unless an equivalent is implemented;
- keep optimization settings explicit rather than relying on ambient defaults.

Do not silently discard flags that affect ABI, visibility, symbol export, standard semantics, or optimization.

## Symbol export/import handling

Prove how the CFFI `PyInit_<module>` symbol is exported from the generated PE DLL. Prefer normal generated-source annotations if TinyCC honors them. Otherwise generate a minimal module `.def` file deterministically from the known module init symbol.

Python API imports must come from packaged `python3.def`.

## Diagnostics

Capture per JIT:

- TinyCC exact revision/version;
- full compile and link command lines;
- include search roots;
- `.def` files used;
- generated `.pyd` import/export table;
- compiler exit output;
- adapter-selected standard/optimization flags.

CI diagnostics should make it impossible to confuse a TinyCC build with LLVM-MinGW/MSVC fallback.

## Tasks

1. Implement a private TinyCC `CCompiler` subclass.
2. Register it only inside the owned runtime activation context.
3. Implement compile/link option translation.
4. Implement deterministic `.def` handling for Python imports and, if needed, extension exports.
5. Add tests for paths with spaces and non-default temporary directories.
6. Add negative tests proving unsupported important flags fail loudly.
7. Add diagnostics and PE verification.
8. Ensure runtime activation restores all process state after JIT.

## Exit criteria

Phase 3 passes when unmodified CFFI/FFCx callers can compile through the TinyCC backend without global configuration, no host compiler can be selected accidentally, and the adapter is small enough to review as a dedicated FEniCS Windows integration layer.