# Phase 4 stage 5

Stage 4 qualified at **112.1238 MiB**, **3.9238 MiB** above the early gate.

The pinned LLVM 23.1 source explicitly categorizes Clang resource headers in
`clang/lib/Headers/CMakeLists.txt`. The installed Stage-4 package still
contains about 7.44 MiB of these headers even though the host build targets X86
only.

Stage 5 removes only the pinned resource groups for non-x86 architectures and
GPU/offload languages:

- ARM/AArch64, Hexagon, LoongArch, MIPS, PowerPC, RISC-V, SystemZ/zOS, VE and
  WebAssembly;
- CUDA, HIP, HLSL, OpenCL, SPIR-V, generic GPU, OpenMP-device and LLVM offload;
- LLVM-libc wrapper resources not used by the Windows FFCx C contract.

It retains all pinned core, x86, Windows and utility Clang resource headers,
including the full x86 intrinsic set, plus the already-qualified C/UCRT target
sysroot. Expected removal from the Stage-4 manifest is about **4.25 MiB**.

The candidate must reproduce independently and pass relocation smoke plus the
complete Python 3.12-3.14 private qualification. Phase 5 remains blocked until
that completes and the installed backend measures <=108.2 MiB.
