# Phase 7: standalone/Nuitka staging

## Objective

Stage the minimized JIT compiler and all Python development/build-backend inputs required by CFFI into the standalone/Nuitka bundle, then prove fresh JIT works independently of the original conda/build environment.

The existing standalone build itself may still use VS2022. This phase concerns the compiler required by the produced runtime.

## Required staged inputs

At minimum stage:

- minimized LLVM-MinGW toolchain;
- CPython headers matching the Python embedded in the bundle;
- GNU/LLVM-MinGW-compatible Python import library selected by Phase 1;
- CFFI runtime code;
- setuptools/distutils implementation required by CFFI runtime compilation on Python 3.12+;
- FFCx/UFL/UFCx runtime data required by JIT.

Ensure Nuitka explicitly includes dynamically imported build-backend modules such as setuptools rather than assuming static discovery retains them.

A conceptual bundle:

```text
application/
  <DOLFINx/PETSc/Python runtime>
  <FFCx/UFL/CFFI/setuptools runtime code>
  python-dev/
    <matching CPython headers>
    <selected GNU Python import library>
  jit/
    <clang>
    <lld>
    <mingw-w64/UCRT C headers>
    <mingw-w64/UCRT import libraries>
    <Clang resource files>
```

## Runtime discovery

Reuse the Phase 4 helper.

It must resolve compiler and Python development inputs relative to the bundle. It must explicitly pass staged include/library locations into CFFI/setuptools rather than relying on `sysconfig` paths that can point back to the original conda environment.

The produced runtime must not require:

- conda activation;
- Visual Studio;
- Windows SDK installation;
- registry compiler discovery;
- `vcvarsall.bat`;
- `vswhere.exe`.

## Acceptance test

1. Build the standalone bundle with the existing Windows runner/build setup.
2. Clear the bundled FFCx cache.
3. Rename, move, or otherwise make the original conda/build prefix inaccessible.
4. Launch the bundle under the same sanitized runtime environment used by package-level JIT tests.
5. Force a fresh form compilation.
6. Inspect the generated `.pyd` dependencies and Python DLL import.
7. Repeat from cache.
8. Record the incremental bundle size attributable to JIT support.

## Tasks

1. Extend `scripts/fenicsx-nuitka.ps1` or its successor to stage the minimized JIT tree.
2. Stage matching CPython headers/import library.
3. Include CFFI/setuptools runtime build-backend modules explicitly.
4. Wire bundle-relative paths into the Phase 4 runtime helper.
5. Add fresh-cache standalone JIT CI.
6. Add original-prefix-inaccessible validation.
7. Record bundle size delta and dependency inspection.

## Exit criteria

Phase 7 is complete when:

- the standalone bundle performs a fresh FFCx JIT with the original build prefix inaccessible;
- no Visual Studio or host Windows SDK compiler inputs participate;
- all development inputs resolve from the bundle;
- generated JIT modules have expected PE imports;
- cache reuse works;
- the incremental standalone JIT footprint is recorded.

After this phase, fold the proven checks into the normal package/release CI gates.
