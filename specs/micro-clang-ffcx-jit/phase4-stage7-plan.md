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
