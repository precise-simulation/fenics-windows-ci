# Phase 4: switch the DOLFINx runtime dependency

## Objective

After the deterministic runtime helper is established in Phase 3, replace the Windows `fenics-dolfinx` runtime dependency that currently brings in the generic C compiler with the dedicated LLVM-MinGW JIT package.

Native package build requirements remain on VS2022.

## Runtime dependencies

CFFI runtime compilation on Python 3.12+ requires setuptools' vendored distutils implementation. The conda-forge `cffi` package does not guarantee `setuptools` as a runtime dependency, so declare it explicitly.

Conceptually:

```yaml
run:
  - fenics-jit-llvm-mingw
  - cffi
  - setuptools
  - fenics-ffcx
  - ...
```

Pin or constrain CFFI/setuptools when required by the verified JIT integration. Prefer keeping version-sensitive behavior behind the owned adapter/helper from Phase 1 so dependency updates can be tested in isolation.

## Constraints

Do not change:

- VS2022 build requirements for PETSc, DOLFINx, Basix, or other native packages;
- Linux/macOS runtime compiler behavior unless required by an upstreamable cross-platform fix.

The installed Windows runtime must perform FFCx JIT without conda compiler activation.

## Tasks

1. Add `fenics-jit-llvm-mingw` to the Windows `fenics-dolfinx` runtime requirements.
2. Remove the generic Windows runtime C compiler dependency.
3. Add explicit runtime `setuptools`.
4. Add any verified CFFI/setuptools compatibility constraint needed by the JIT adapter.
5. Build `fenics-dolfinx` through the normal repository stack workflow.
6. Verify solved runtime metadata contains the dedicated JIT package and no unintended full compiler stack.
7. Run fresh Poisson JIT on CPython 3.12, 3.13, and 3.14.

## Exit criteria

Phase 3 is complete when:

- `fenics-dolfinx` runtime metadata no longer pulls the generic Windows compiler dependency;
- `fenics-jit-llvm-mingw`, `cffi`, and `setuptools` are explicit runtime inputs;
- the native FEniCSx build path remains unchanged;
- fresh JIT passes on all supported Windows CPython versions.
