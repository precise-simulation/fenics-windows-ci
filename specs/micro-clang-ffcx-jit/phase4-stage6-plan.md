# Phase 4 stage 6: ThinLTO host minimization

Stage 5 qualified at **107.8796 MiB** and established the current
default-candidate compiler/sysroot payload. The stronger <=81.2 MiB target was
not reached primarily because the retained host Clang/LLVM closure dominates
the remaining footprint.

Stage 6 tests whether LLVM ThinLTO can reduce that host closure without changing
the generated FFCx target-code policy.

## Candidate

Rebuild the same pinned LLVM/Clang/LLD toolchain with:

- X86 only;
- Clang + LLD only;
- `MinSizeRel`;
- shared `libLLVM`;
- `CLANG_LINK_CLANG_DYLIB=OFF`;
- upstream llvm-mingw `--thinlto` (`LLVM_ENABLE_LTO=thin`);
- the existing Stage-4 `llvm-strip --strip-all` host-PE pass.

Then reapply, unchanged:

1. the qualified Stage-AW reductions;
2. the qualified Stage-3 trace-driven target-sysroot pruning using the retained
   Python 3.12-3.14 closure evidence;
3. the qualified Stage-5 non-x86/GPU/offload Clang resource-header pruning.

Generated FFCx modules continue to use the already-qualified runtime `-O2`
policy. ThinLTO applies only while building the host compiler.

## Decision path

The dedicated Stage-6 workflow must:

1. build the ThinLTO host toolchain from the same immutable source identities;
2. strip the same retained PE closure;
3. reapply the exact qualified pruning stages;
4. construct the candidate independently twice and require
   `metadata.json`, `manifest.csv` and `size.txt` hash equality;
5. run relocation/package smoke;
6. compare the finalized complete backend to the qualified Stage-5
   **107.8796 MiB** parent;
7. skip the expensive private matrix if the candidate is not smaller;
8. if smaller, run the complete Python 3.12-3.14 private qualification.

The report records progress against:

- qualified parent: 107.8796 MiB;
- strong target: <=81.2 MiB;
- stretch target: <=54.1 MiB.

## Guardrails

Stage 6 is experimental. The already-qualified implementation at
`b632e35d3114c0787393cfdd04c637bde79897a6` remains authoritative until a
smaller Stage-6 candidate passes the complete private matrix.

Even a privately qualified Stage-6 candidate must not silently replace the
shared-runtime package. Adoption requires fresh downstream selector/cache/
concurrency qualification, paired three-backend performance comparison and the
micro-Clang-only serial/MPI standalone proof because the compiler payload and
cache identity change.

LLVM-MinGW remains the actual default throughout this experiment.
