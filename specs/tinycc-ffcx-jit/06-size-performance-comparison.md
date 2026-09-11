# Phase 6: size and performance comparison

**Status:** proposed.

## Objective

Measure whether TinyCC provides a worthwhile practical advantage over the qualified LLVM-MinGW runtime, not merely whether it can compile FFCx code.

The comparison must separate three costs:

1. bundled compiler footprint;
2. JIT compile/link latency;
3. execution performance of generated finite-element kernels/assembly.

## Reference

Use the qualified LLVM-MinGW Stage AW package as the baseline:

- staged payload: 215.19 MiB;
- installed package content: 216.43 MiB;
- compressed `.conda`: 51.34 MiB.

TinyCC must remain below 25% of the LLVM-MinGW installed footprint (about 54 MiB) to qualify as materially smaller. Record exact staged, installed, and compressed values from CI; do not rely on upstream archive size alone.

## Footprint measurements

For each backend record:

- package staged bytes;
- installed bytes;
- compressed package bytes;
- standalone incremental bytes;
- file/category breakdown;
- headers/runtime/import-definition share;
- adapter/helper share.

Avoid aggressive TinyCC minimization until the full functional matrix passes. The upstream Windows TCC package is already small; correctness has higher value than shaving marginal files.

## JIT latency benchmark

Measure cold and warm compilation for the same generated-source corpus.

Record separately:

- FFCx code-generation time;
- CFFI wrapper generation time;
- compiler time;
- linker time;
- total first-use JIT latency;
- cache-hit load latency.

Use repeated runs and report median plus distribution/percentiles. TinyCC is expected to have a strong compile-latency advantage, but the measurement should establish the actual benefit in this workload.

## Generated-code/runtime benchmark

TinyCC's smaller/faster compiler is useful only if the generated kernels are not prohibitively slow.

Benchmark at least:

- scalar Poisson assembly;
- vector elasticity-like form;
- higher-order element assembly;
- interior/exterior facet workloads;
- coefficient-heavy form;
- a representative small end-to-end solve where assembly is measurable.

Keep PETSc solver configuration identical. Separate assembly/kernel time from linear-solver time so the compiler-generated code is measured directly.

Run enough iterations to amortize JIT and startup when comparing steady-state execution.

## Decision thresholds

### Default-backend candidate

TinyCC may be considered for the default only if:

- full Phase 5 coverage is green;
- installed compiler footprint is <=25% of LLVM-MinGW;
- representative assembly/runtime benchmarks are generally within 25% of LLVM-MinGW;
- no severe outlier/regression exists in an important form family;
- JIT latency and/or standalone footprint provides a clear user benefit.

### Compact/fallback candidate

TinyCC may still be useful as a compact backend when:

- correctness and ABI gates are fully green;
- installed compiler footprint is <=25% of LLVM-MinGW;
- representative generated-code runtime is normally no worse than 3x LLVM-MinGW;
- the footprint/JIT-latency advantage is substantial.

This profile is especially relevant for standalone distribution where package size matters more than peak kernel performance.

### Reject

Reject TinyCC for shipping if:

- runtime performance is severely or unpredictably worse;
- numerical behavior differs materially;
- unsupported compiler semantics require ongoing generated-source rewrites;
- CRT/ABI uncertainty remains;
- the actual packaged footprint is not materially smaller after required headers/support are included.

## Tasks

1. Add side-by-side package size reporting.
2. Add cold/warm JIT timing around identical generated sources.
3. Add kernel/assembly microbenchmarks.
4. Add representative end-to-end solve timing with assembly separated.
5. Run multiple repetitions and publish raw timing data as artifacts.
6. Compare Python versions to detect version-specific overhead.
7. Record the final classification: default candidate, compact/fallback candidate, or reject.

## Exit criteria

Phase 6 is complete when the TinyCC vs LLVM-MinGW tradeoff is quantitatively documented and a classification is justified by size, JIT latency, and generated-code execution measurements rather than compiler reputation or archive size.