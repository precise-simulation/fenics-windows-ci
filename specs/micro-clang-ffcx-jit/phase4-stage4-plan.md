# Phase 4 stage 4

Stage 3 qualified at **112.938 MiB**, only **4.738 MiB** above the early
continuation gate.

Stage 4 is a separate host-only experiment:

1. rebuild the already-qualified MinSizeRel/X86-only host profile;
2. use that build's own `llvm-strip --strip-all` on only the retained host
   compiler/runtime PE closure (Clang, LLD, LLVM, llvm-readobj, llvm-dlltool,
   libc++, libunwind);
3. record before/after bytes for every stripped file;
4. package the stripped host toolchain, then reapply the exact qualified
   Stage-AW and Stage-3 target-sysroot reductions;
5. reconstruct independently and require metadata/manifest/size hash identity;
6. rerun relocation smoke and the complete Python 3.12-3.14 private
   qualification.

The generated FFCx target-code flags and sysroot retention policy are unchanged.
No production selector/default change is permitted until the complete candidate
is <=108.2 MiB and the blocking matrix passes.
