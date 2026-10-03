# Micro-Clang default switch

## Scope

This follow-up changes the normal Windows FEniCS JIT backend from LLVM-MinGW to
the qualified Full-LTO micro-Clang package released from Stage 7.

Release prerequisite:

- package: `fenics-jit-micro-clang-20260826-h9490d1a_1.conda`
- SHA-256: `d8a3510eb08615cb890dbf8f6da8b0d26f573e16a7b0bbee657edf563d40ad01`
- publication workflow: `micro-clang-release` run `37112734709` — passed.

## Production changes

- shared selector default: `micro-clang`;
- shared selector default: `micro-clang` is the production default;\n- the legacy `fenics_jit_runtime.py` compatibility facade keeps its historical\n  LLVM-MinGW fallback when no toolchain root is supplied, so pinned/reference\n  environments without micro-Clang remain reproducible;
- Windows `fenics-dolfinx` runtime dependency:
  `fenics-jit-micro-clang ==20260826`;
- LLVM-MinGW remains installable explicitly but is no longer part of a normal
  DOLFINx environment;
- TinyCC remains an explicit compact alternative;
- routine stack CI consumes the published micro-Clang package rather than
  rebuilding either micro-Clang or LLVM-MinGW.

## Default-path release gates

The stack PR must prove the actual normal installation, with no
`FENICS_JIT_COMPILER` override:

1. Python 3.12, 3.13 and 3.14 install `fenics-dolfinx` with
   `fenics-jit-runtime` + `fenics-jit-micro-clang`;
2. neither `fenics-jit-llvm-mingw` nor `fenics-jit-tinycc` is installed;
3. fresh serial FFCx JIT selects micro-Clang under poisoned host compiler/SDK
   variables;
4. cache reuse performs no second compiler invocation;
5. two-rank MPI uses rank 0 as compile owner and rank 1 as cache consumer;
6. broad cold/cache timing sanity bounds catch catastrophic regressions while
   Stage-7 paired benchmarks remain the quantitative performance record;
7. the micro-Clang-only Nuitka standalone bundle passes serial and two-rank MPI
   with `FENICS_JIT_COMPILER` unset and the build prefix inaccessible.

The default switch does not remove LLVM-MinGW qualification or packaging; it
only removes LLVM-MinGW from the normal dependency/default path.
