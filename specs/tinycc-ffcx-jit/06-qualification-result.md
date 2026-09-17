# Phase 6 qualification result

**Decision:** COMPLETE — TinyCC qualifies as a **compact/fallback candidate**, not as a default-backend candidate.

## Qualified revision

- repository head: `ee63a1e0a49012e56ba312a9b72c533965738ad0`
- branch: `impl/tinycc-ffcx-jit-phase1`
- workflow: `tinycc-jit` #79
- run: `35202679462`
- principal regression workflow: `stack` #316
- principal regression run: `35202679484`
- pinned TinyCC revision: `0fb54300b56512754221d80adda85ddb9815bceb`
- supported blocking Python matrix: 3.12, 3.13, 3.14
- immutable LLVM-MinGW reference: Stage AW / stack #231 (`34580520920`), 216.43 MiB installed

Both exact-head workflows completed successfully. The Phase-6 benchmark ran only after the Phase-5 functional gates in each supported TinyCC qualification job.

## Final footprint

The integrated TinyCC backend is materially smaller than the pinned Stage-AW LLVM-MinGW reference:

| Measurement | TinyCC |
| --- | ---: |
| backend staged payload | 2,313,635 bytes / 2.206 MiB |
| backend installed payload | 2,313,635 bytes / 2.206 MiB |
| compressed `.conda` | 633,746 bytes / 0.604 MiB |
| common runtime | 23,007 bytes / 0.0219 MiB |
| standalone incremental runtime + TinyCC | 2,336,642 bytes / 2.228 MiB |
| percent of pinned Stage-AW installed footprint | 1.019% |

The <=25% footprint gate therefore passes with substantial margin. The current branch LLVM-MinGW backend remains about 215.48 MiB installed; the immutable Stage-AW decision baseline remains 216.43 MiB as required by the Phase-6 specification.

TinyCC backend payload composition is dominated by headers (1,354,852 bytes), followed by compiler binaries (730,112 bytes), runtime/import definitions (154,932 bytes), adapter/helpers/metadata (46,807 bytes), and license material (26,932 bytes).

## JIT latency

Cold first-use JIT is consistently much faster with TinyCC. Median TinyCC/LLVM-MinGW total cold-JIT ratios by form family, aggregated across Python 3.12-3.14, are:

| Form family | median TinyCC / LLVM-MinGW cold-JIT ratio |
| --- | ---: |
| scalar Poisson | 0.217x |
| vector elasticity | 0.236x |
| higher-order P3 | 0.217x |
| interior/exterior facet DG1 | 0.232x |
| coefficient-heavy | 0.257x |

Across individual supported interpreters/form families, cold-JIT ratios range from about 0.198x to 0.291x. Compiler/link time itself is roughly 0.08-0.10x LLVM-MinGW in the measured cases. Warm cache lookup/load also remains faster in this run, with per-version median ratios of about 0.87x (3.12), 0.77x (3.13), and 0.72x (3.14).

## Generated-code execution performance

The generated-code tradeoff is significant and stable rather than measurement noise. Median assembly ratios across Python 3.12-3.14 are:

| Form family | median ratio across Python versions | observed range |
| --- | ---: | ---: |
| interior/exterior facet DG1 | 1.274x | 1.179-1.280x |
| scalar Poisson | 1.456x | 1.369-1.565x |
| vector elasticity | 1.837x | 1.755-2.055x |
| coefficient-heavy | 2.748x | 2.595-3.476x |
| higher-order P3 | 4.412x | 4.138-6.235x |

The TinyCC timing distributions are narrow enough that the higher-order regression cannot reasonably be treated as runner noise: TinyCC assembly IQR width is generally about 0.5-5% of the median. The P3 slowdown reproduces on all three supported Python versions.

Only one of the five family-level aggregate medians is within the default-candidate 25% runtime envelope. Four of five family-level medians are within the compact-backend 3x envelope; the higher-order family is a persistent documented outlier.

Per-interpreter provisional classification from the benchmark harness was:

| Python | provisional classification | median assembly ratio | worst assembly ratio |
| --- | --- | ---: | ---: |
| 3.12 | reject | 2.055x | 6.235x |
| 3.13 | compact/fallback candidate | 1.837x | 4.412x |
| 3.14 | compact/fallback candidate | 1.755x | 4.138x |

The final Phase-6 classification is based on the form-family behavior across the complete supported matrix rather than majority-voting those per-interpreter provisional labels. The result does not satisfy the default-backend criteria, but the combination of approximately 1% compiler footprint, roughly 4-5x faster cold JIT, stable numerical results, and four of five representative form-family medians within 3x supports continued evaluation as a compact/optional backend. The higher-order regression must remain an explicit release limitation.

## Representative end-to-end solve

The Poisson solve confirms that PETSc solver behavior itself is effectively unchanged while generated assembly is slower:

| Metric | TinyCC / LLVM-MinGW range across Python 3.12-3.14 |
| --- | ---: |
| assembly | 1.316-1.586x |
| linear solver | 0.990-1.018x |
| total solve | 1.200-1.359x |

Numerical matrix norms and solution norms matched under the existing Phase-6 tolerances.

## Benchmark path correction

The first Phase-6 exact-head run (`tinycc-jit` #78) reached the new benchmark after the functional gates but failed when the long Phase-4A work/cache path pushed a generated TinyCC output path beyond the practical Windows path limit for the `interior_exterior_facet_dg1` case.

Commit `ee63a1e0a49012e56ba312a9b72c533965738ad0` changed only the Phase-6 physical cache root to the short evidence path `phase4a-evidence/p6c`. Logical form identities, compiler inputs, cache-identity policy, benchmark repetitions, runtime packages, and decision thresholds were unchanged. Exact-head run #79 then completed the full benchmark on Python 3.12-3.14.

## Non-blocking reference results

These expected results do not change the Phase-6 classification:

- TinyCC 0.9.27 formal-release reference remains non-blocking and fails in its reference bootstrap path; the qualified backend remains the pinned development revision.
- Python 3.15 preview remains informational/non-blocking and currently fails while installing/resolving the FEniCS runtime environment; the blocking matrix remains Python 3.12-3.14.

## Boundary of this decision

Phase 6 is complete. TinyCC is **not** qualified to replace LLVM-MinGW as the normal/default JIT backend based on the measured generated-code performance.

The next ordered gate is Phase 7, `07-standalone-release-decision.md`. Phase 7 should evaluate the TinyCC backend specifically as an optional fallback or compact standalone backend, with LLVM-MinGW remaining the normal/reference backend. It must retain the higher-order performance limitation above in the final release decision.

This result does not change production defaults, merge PR #11, or mark the draft PR ready for review.