# Phase 4 stage 7: Full-LTO host minimization

Stage 6 qualified ThinLTO as the preferred micro-Clang payload, but the complete
backend improved by only about 1.56% relative to its Stage-5 parent. Stage 7
tests LLVM full LTO before considering more invasive compiler specialization.

## Controlled change

Hold all qualified inputs and runtime policy constant:

- pinned LLVM/Clang/LLD and mingw-w64 source identities;
- X86-only MinSizeRel host build;
- shared `libLLVM`;
- no `libclang-cpp`;
- existing `llvm-strip --strip-all`;
- the exact qualified Stage-AW, Stage-3 sysroot and Stage-5 resource-header
  reductions;
- unchanged generated FFCx `-O2` target-code policy.

Change only upstream llvm-mingw `--thinlto` to `--lto`
(`LLVM_ENABLE_LTO=full`).

## First gate: size only

Full LTO has materially higher link cost than the ordinary host build, and
ThinLTO already showed diminishing returns. Therefore Stage 7 initially runs
only:

1. the Full-LTO host build;
2. the existing strip pass;
3. the exact qualified pruning sequence;
4. relocation/package smoke;
5. complete-payload measurement against the qualified Stage-6 ThinLTO artifact.

The workflow records the exact byte delta and largest retained files.

Stage 6 remains authoritative during this experiment. Do not run the expensive
Python 3.12-3.14 private/shared-runtime matrices, paired performance benchmark,
or standalone/MPI qualification unless the measured Full-LTO result shows a
material additional size reduction that justifies adoption work.

The strong <=81.2 MiB and stretch <=54.1 MiB objectives remain aspirational.


## Qualification result

Stage 7 is complete and qualified.

- Full-LTO source build: run `37093105472`, passed.
- Focused measurement retry: run `37100266040`, passed.
- Complete pre-conda backend: **103.8251 MiB**.
- Reduction versus qualified ThinLTO: **2.3765 MiB / 2.2377%**.
- Conda package: **103.98 MiB installed / 30.41 MiB compressed**.
- Paired installed backend: **103.8560 MiB**.
- Python 3.12-3.14 shared-runtime integration: passed.
- Paired three-backend performance: passed.
- Micro-Clang-only serial/MPI Nuitka standalone qualification: passed in
  downstream run `37100978194`.
- Standalone incremental micro-Clang payload: **103.8633 MiB**.

The strong <=81.2 MiB target remains unmet. Full LTO nevertheless provides a
larger incremental reduction than ThinLTO without a measured generated-code or
runtime-quality regression, so Full LTO supersedes ThinLTO as the preferred
qualified micro-Clang build profile.

The cost is source-build time: the observed Full-LTO host build was about
67m20s versus about 49m14s for ThinLTO. Completed Stage-7 experiment workflows
are therefore retained as manual reproducibility workflows rather than normal
pull-request checks.
